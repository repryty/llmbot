import logging
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands, ui

from bot.core.config import settings
from bot.core.danbooru_client import fetch_tag_frequencies

logger = logging.getLogger(__name__)

_CAT_LABEL = {"general": "General 🏷️", "style": "Style 🎨", "meta": "Meta ⚙️"}
_THRESHOLDS = [1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
_MAX_SELECT_OPTIONS = 25
_EMBED_TAG_PREVIEW = 10  # tags shown inline in embed per category


# ---------------------------------------------------------------------------
# View components
# ---------------------------------------------------------------------------

class ThresholdSelect(ui.Select):
    def __init__(self, view_ref: "DanbooruTagView"):
        self._v = view_ref
        options = [
            discord.SelectOption(
                label=f"{t:.0f}%",
                value=str(t),
                default=(t == view_ref.threshold),
            )
            for t in _THRESHOLDS
        ]
        super().__init__(
            placeholder=f"임계값: {view_ref.threshold:.0f}% 이상",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self._v.threshold = float(self.values[0])
        for cat in self._v.selected:
            visible = {tag for tag, _ in self._v._top_tags(cat)}
            self._v.selected[cat] &= visible
        self._v._rebuild()
        await interaction.response.edit_message(embed=self._v._build_embed(), view=self._v)


class CategorySelect(ui.Select):
    def __init__(self, view_ref: "DanbooruTagView", cat: str, row: int):
        self._v = view_ref
        self._cat = cat
        tags = view_ref._top_tags(cat)
        if tags:
            options = [
                discord.SelectOption(
                    label=f"{tag} ({pct:.1f}%)"[:100],
                    value=tag,
                    default=(tag in view_ref.selected[cat]),
                )
                for tag, pct in tags
            ]
            super().__init__(
                placeholder=f"{_CAT_LABEL[cat]} 태그 선택",
                options=options,
                min_values=0,
                max_values=len(options),
                row=row,
            )
        else:
            super().__init__(
                placeholder=f"{_CAT_LABEL[cat]} — 해당 없음",
                options=[discord.SelectOption(label="(없음)", value="_none_")],
                disabled=True,
                row=row,
            )

    async def callback(self, interaction: discord.Interaction):
        self._v.selected[self._cat] = {v for v in self.values if v != "_none_"}
        self._v._rebuild()
        await interaction.response.edit_message(embed=self._v._build_embed(), view=self._v)


class GenerateButton(ui.Button):
    def __init__(self, view_ref: "DanbooruTagView"):
        super().__init__(
            label="네거티브 프롬프트 생성",
            style=discord.ButtonStyle.green,
            emoji="📋",
            row=4,
        )
        self._v = view_ref

    async def callback(self, interaction: discord.Interaction):
        all_tags: list[str] = []
        for cat in ("general", "style", "meta"):
            all_tags.extend(sorted(self._v.selected[cat]))
        if not all_tags:
            await interaction.response.send_message(
                "선택된 태그가 없습니다. 아래 드롭다운에서 태그를 선택하세요.", ephemeral=True
            )
            return
        prompt = ", ".join(all_tags)
        await interaction.response.send_message(
            f"**네거티브 프롬프트** ({len(all_tags)}개 태그)\n```\n{prompt}\n```",
            ephemeral=True,
        )


class ResetButton(ui.Button):
    def __init__(self, view_ref: "DanbooruTagView"):
        super().__init__(
            label="선택 초기화",
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            row=4,
        )
        self._v = view_ref

    async def callback(self, interaction: discord.Interaction):
        for cat in self._v.selected:
            self._v.selected[cat] = set()
        self._v._rebuild()
        await interaction.response.edit_message(embed=self._v._build_embed(), view=self._v)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class DanbooruTagView(ui.View):
    def __init__(
        self,
        counts: dict[str, dict[str, int]],
        total_posts: int,
        artist: str,
    ):
        super().__init__(timeout=300)
        self.counts = counts
        self.total_posts = total_posts
        self.artist = artist
        self.threshold = 5.0
        self.selected: dict[str, set[str]] = {"general": set(), "style": set(), "meta": set()}
        self.message: Optional[discord.Message] = None
        self._rebuild()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _top_tags(self, cat: str) -> list[tuple[str, float]]:
        """Top _MAX_SELECT_OPTIONS tags above threshold, sorted by freq desc."""
        if self.total_posts == 0:
            return []
        result = [
            (tag, count / self.total_posts * 100)
            for tag, count in self.counts.get(cat, {}).items()
            if count / self.total_posts * 100 >= self.threshold
        ]
        return sorted(result, key=lambda x: x[1], reverse=True)[:_MAX_SELECT_OPTIONS]

    def _count_above(self, cat: str) -> int:
        if self.total_posts == 0:
            return 0
        return sum(
            1 for count in self.counts.get(cat, {}).values()
            if count / self.total_posts * 100 >= self.threshold
        )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _rebuild(self):
        self.clear_items()
        self.add_item(ThresholdSelect(self))
        for i, cat in enumerate(("general", "style", "meta"), start=1):
            self.add_item(CategorySelect(self, cat, row=i))
        self.add_item(GenerateButton(self))
        self.add_item(ResetButton(self))

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"Danbooru 태그 분석 — {self.artist}",
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"포스트 {self.total_posts}개 수집 | 임계값 {self.threshold:.0f}% 이상 | 카테고리별 최대 {_MAX_SELECT_OPTIONS}개 표시"
        )

        if self.total_posts == 0:
            embed.description = "해당 작가의 포스트를 찾을 수 없습니다."
            return embed

        for cat in ("general", "style", "meta"):
            tags = self._top_tags(cat)
            total_above = self._count_above(cat)
            sel_count = len(self.selected[cat])
            name = f"{_CAT_LABEL[cat]}  ({total_above}개 해당 / {sel_count}개 선택)"

            if not tags:
                embed.add_field(name=name, value="*임계값 이상 태그 없음*", inline=False)
                continue

            preview = "  ".join(f"`{tag}` {pct:.1f}%" for tag, pct in tags[:_EMBED_TAG_PREVIEW])
            extra = f"\n*… 외 {total_above - _EMBED_TAG_PREVIEW}개*" if total_above > _EMBED_TAG_PREVIEW else ""
            embed.add_field(name=name, value=preview + extra, inline=False)

        all_selected = [t for cat in ("general", "style", "meta") for t in sorted(self.selected[cat])]
        if all_selected:
            display = ", ".join(f"`{t}`" for t in all_selected[:20])
            if len(all_selected) > 20:
                display += f" … (+{len(all_selected) - 20}개)"
            embed.add_field(
                name=f"✅ 선택된 태그 ({len(all_selected)}개)",
                value=display,
                inline=False,
            )

        return embed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class DanbooruCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _check_whitelist(self, interaction: discord.Interaction):
        if interaction.user.id not in settings.whitelist_ids:
            raise app_commands.CheckFailure("이 명령어는 허가된 사용자만 사용할 수 있습니다.")

    @app_commands.command(
        name="danbooru_tags",
        description="특정 작가의 Danbooru 태그 빈도를 분석해 네거티브 프롬프트를 만듭니다.",
    )
    @app_commands.describe(artist="Danbooru 작가 태그 (예: kantoku)")
    async def danbooru_tags(self, interaction: discord.Interaction, artist: str):
        self._check_whitelist(interaction)
        await interaction.response.defer(thinking=True, ephemeral=True)

        artist = artist.strip().lower().replace(" ", "_")
        try:
            counts, total_posts = await fetch_tag_frequencies(
                artist,
                max_pages=3,
                login=settings.DANBOORU_LOGIN,
                api_key=settings.DANBOORU_API_KEY,
            )
        except Exception as e:
            logger.exception("danbooru_tags 오류 | artist=%s", artist)
            await interaction.followup.send(f"Danbooru API 오류: `{e}`", ephemeral=True)
            return

        view = DanbooruTagView(counts, total_posts, artist)
        message = await interaction.followup.send(
            embed=view._build_embed(),
            view=view,
            ephemeral=True,
            wait=True,
        )
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(DanbooruCog(bot))
