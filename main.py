from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import re
import random
import aiohttp
from PIL import Image, ImageDraw, ImageFont
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.message_components import Record, Reply, Image as AstrImage
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

ALLOWED_EXT = {".mp3", ".wav", ".ogg", ".silk", ".amr"}
PAGE_SIZE = 15
IMAGE_PAGE_SIZE = 40         # 图片模式每页显示数量
FONT_SIZE = 28
IMAGE_WIDTH = 1360
IMAGE_BG_COLOR_TOP = (246, 248, 252)
IMAGE_BG_COLOR_BOTTOM = (235, 240, 247)
IMAGE_TEXT_COLOR = (34, 41, 55)


@dataclass
class AiriListAllVoicesTool(FunctionTool[AstrAgentContext]):
    """列出当前插件中所有可用的语音名称。"""
    name: str = "airi_list_all_voices"
    description: str = "列出本插件加载的全部语音名称，供 LLM 选择使用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": [],
        }
    )
    plugin: Any = None

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map:
            return "当前没有可用语音。"
        names = sorted(self.plugin.voice_map.keys())
        return "当前可用语音名称列表：\n" + "\n".join(names)


@dataclass
class AiriSearchVoicesTool(FunctionTool[AstrAgentContext]):
    """根据关键词筛选语音名称。"""
    name: str = "airi_search_voices"
    description: str = "根据用户给出的关键词，在本插件的语音库中筛选匹配的语音名称。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "用户给出的语音关键词，用于模糊匹配语音名称。",
                }
            },
            "required": ["keyword"],
        }
    )
    plugin: Any = None

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map:
            return "当前没有可用语音。"
        keyword = (kwargs.get("keyword") or "").strip()
        if not keyword:
            return "请提供要搜索的语音关键词。"
        keyword_lower = keyword.lower()
        matched = [
            name for name in self.plugin.voice_map.keys() if keyword_lower in name.lower()
        ]
        if not matched:
            return f"未找到包含「{keyword}」的语音名称。"
        matched.sort()
        return f"根据关键词「{keyword}」筛选到的语音名称：\n" + "\n".join(matched)


@dataclass
class AiriSendVoiceTool(FunctionTool[AstrAgentContext]):
    """根据指定名称直接向当前会话发送语音。"""
    name: str = "airi_send_voice"
    description: str = "根据指定的语音名称，直接向当前会话发送对应的语音消息。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要发送的语音名称，必须是已存在的语音列表中的一个。",
                }
            },
            "required": ["name"],
        }
    )
    plugin: Any = None

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        if not self.plugin or getattr(self.plugin, "trigger_mode", None) != "llm":
            return "当前未开启 LLM 触发模式，本工具暂不可用。"
        if not self.plugin.voice_map:
            return "当前没有可用语音。"
        name = (kwargs.get("name") or "").strip()
        if not name:
            return "请提供要发送的语音名称。"
        path = self.plugin.voice_map.get(name)
        if not path:
            return f"语音「{name}」不存在，请先使用列出/搜索工具确认可用名称。"
        try:
            agent_ctx = context.context.context
            event = context.context.event
        except Exception:
            agent_ctx = None
            event = None
        if agent_ctx is None or event is None:
            return f"无法获取当前会话上下文，未能发送语音「{name}」。"
        try:
            await agent_ctx.send_message(
                event.unified_msg_origin,
                MessageChain([Record.fromFileSystem(path)]),
            )
            logger.debug(f"[AiriVoice] LLM 工具发送语音：'{name}' → {path}")
            return ""
        except FileNotFoundError as e:
            logger.error(f"[AiriVoice] 文件不存在（LLM 工具） '{name}': {e}")
            return f"语音文件不存在：{name}"
        except Exception as e:
            logger.error(f"[AiriVoice] LLM 工具发送失败 '{name}': {e}")
            return f"语音发送失败：{type(e).__name__}"


@register(
    "airi_voice",
    "lidure",
    "输入关键词发送对应语音",
    "2.4",
    "https://github.com/Lidure/astrbot_plugin_airi_voice",
)
class AiriVoice(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_dir = Path(__file__).parent
        self.voice_dir = self.plugin_dir / "voices"
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_airi_voice")
        self.user_added_dir = self.data_dir / "user_added"
        self.user_added_dir.mkdir(parents=True, exist_ok=True)
        self.extra_voice_dir = self.data_dir / "extra_voices"
        self.extra_voice_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[AiriVoice] 数据目录：{self.data_dir}")

        self.config = config or {}
        self.trigger_mode = self.config.get("trigger_mode", "direct")
        if self.trigger_mode not in {"prefix", "direct", "llm"}:
            logger.warning(f"[AiriVoice] 无效 trigger_mode，强制使用 direct")
            self.trigger_mode = "direct"

        self.admin_mode = self.config.get("admin_mode", "whitelist")
        if self.admin_mode not in {"all", "admin", "whitelist"}:
            self.admin_mode = "whitelist"

        whitelist_raw = self.config.get("admin_whitelist", "")
        if isinstance(whitelist_raw, str):
            self.admin_whitelist: Set[str] = set(
                line.strip() for line in whitelist_raw.splitlines() if line.strip()
            )
        elif isinstance(whitelist_raw, list):
            self.admin_whitelist: Set[str] = set(str(x).strip() for x in whitelist_raw if str(x).strip())
        else:
            self.admin_whitelist: Set[str] = set()

        self.llm_select_mode = self.config.get("llm_select_mode", "list")
        if self.llm_select_mode not in {"list", "keyword"}:
            logger.warning(f"[AiriVoice] 无效 llm_select_mode，强制使用 list")
            self.llm_select_mode = "list"

        self.auto_reply_voice_enabled = self.config.get("auto_reply_voice_on_bot_message", False)
        self.list_as_image = self.config.get("list_as_image", False)   # ← 新增

        self.voice_map: Dict[str, str] = {}
        self.sorted_keys: List[str] = []

        self._load_local_voices()
        self._load_user_added_voices()
        self._load_web_voices(self.config)
        self._update_sorted_keys()

        self.last_pool_len = len(self.config.get("extra_voice_pool", []))

        if self.trigger_mode == "llm":
            llm_tools = []
            if self.llm_select_mode == "list":
                llm_tools.append(AiriListAllVoicesTool(plugin=self))
            else:
                llm_tools.append(AiriSearchVoicesTool(plugin=self))
            llm_tools.append(AiriSendVoiceTool(plugin=self))
            try:
                self.context.add_llm_tools(*llm_tools)
                logger.info(f"[AiriVoice] 已为 LLM 注册 {len(llm_tools)} 个语音工具，模式：{self.llm_select_mode}")
            except Exception as e:
                logger.error(f"[AiriVoice] 注册 LLM 工具失败：{e}")

        if self.auto_reply_voice_enabled:
            logger.info("[AiriVoice] 已启用 bot 回复自动追加语音功能")

        logger.info(f"[AiriVoice] 初始化完成，共 {len(self.voice_map)} 个语音，权限模式：{self.admin_mode}，列表图片模式：{'开启' if self.list_as_image else '关闭'}")

    # ==================== 原有辅助方法（未修改） ====================

    def _get_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        try:
            return event.get_sender_id()
        except (AttributeError, TypeError):
            pass
        try:
            return event.message_obj.sender.user_id
        except AttributeError:
            pass
        user_id = getattr(event, 'sender_id', None) or getattr(event, 'user_id', None)
        return str(user_id) if user_id else None

    def _get_reply_id(self, event: AstrMessageEvent) -> Optional[int]:
        for seg in event.get_messages():
            if isinstance(seg, Reply):
                try:
                    return int(seg.id)
                except (ValueError, TypeError):
                    pass
        return None

    async def _get_audio_url(self, event: AstrMessageEvent) -> Optional[str]:
        # ...（保持你原来的实现不变）
        chain = event.get_messages()
        url = None
        def extract_media_url(seg):
            url_ = (getattr(seg, "url", None) or getattr(seg, "file", None) or getattr(seg, "path", None))
            return url_ if url_ and str(url_).startswith("http") else None

        reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
        if reply_seg and hasattr(reply_seg, 'chain') and reply_seg.chain:
            for seg in reply_seg.chain:
                if isinstance(seg, Record):
                    url = extract_media_url(seg)
                    if url: break

        if url is None and hasattr(event, 'bot'):
            if msg_id := self._get_reply_id(event):
                try:
                    raw = await event.bot.get_msg(message_id=msg_id)
                    messages = raw.get("message", [])
                    for seg in messages:
                        if isinstance(seg, dict) and seg.get("type") == "record":
                            if seg_url := seg.get("data", {}).get("url"):
                                url = seg_url
                                break
                except Exception as e:
                    logger.error(f"[AiriVoice] 获取引用消息失败：{e}")
        return url

    async def _download_audio(self, url: str) -> Optional[bytes]:
        try:
            async with aiohttp.ClientSession() as client:
                response = await client.get(url)
                return await response.read()
        except Exception as e:
            logger.error(f"[AiriVoice] 下载音频失败：{e}")
            return None

    def _get_file_ext_from_url(self, url: str) -> str:
        url_lower = url.lower()
        if ".wav" in url_lower: return ".wav"
        elif ".ogg" in url_lower: return ".ogg"
        elif ".silk" in url_lower: return ".silk"
        elif ".amr" in url_lower: return ".amr"
        return ".mp3"

    def _update_sorted_keys(self):
        self.sorted_keys = sorted(self.voice_map.keys())

    def _load_local_voices(self):
        count = 0
        for file_path in self.voice_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    self.voice_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从本地加载 {count} 个语音")

    def _load_user_added_voices(self):
        count = 0
        for file_path in self.user_added_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXT:
                keyword = file_path.stem.strip()
                if keyword:
                    if keyword in self.voice_map:
                        logger.warning(f"[AiriVoice] 用户添加关键词冲突：'{keyword}' 已存在，将覆盖")
                    self.voice_map[keyword] = str(file_path)
                    count += 1
        if count > 0:
            logger.info(f"[AiriVoice] 从用户添加目录加载 {count} 个语音")

    def _load_web_voices(self, config: dict = None):
        if config is None:
            return
        extra_pool = config.get("extra_voice_pool", [])
        if not extra_pool:
            return
        logger.debug(f"[AiriVoice] 网页相对路径池：{extra_pool}")
        loaded = 0
        data_dir_resolved = self.data_dir.resolve()
        for rel_path in extra_pool:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            try:
                abs_path = (self.data_dir / rel_path).resolve()
                if not abs_path.is_relative_to(data_dir_resolved):
                    logger.warning(f"[AiriVoice] 检测到非法路径：{rel_path}")
                    continue
            except (ValueError, OSError) as e:
                logger.warning(f"[AiriVoice] 路径解析失败：{rel_path} - {e}")
                continue
            if abs_path.exists() and abs_path.is_file():
                if abs_path.suffix.lower() not in ALLOWED_EXT:
                    logger.warning(f"[AiriVoice] 忽略非音频文件：{abs_path}")
                    continue
                keyword = abs_path.stem.strip()
                if keyword:
                    self.voice_map[keyword] = str(abs_path)
                    loaded += 1
                    logger.debug(f"[AiriVoice] 网页加载：'{keyword}' → {abs_path}")
            else:
                logger.warning(f"[AiriVoice] 文件不存在：{abs_path} (相对：{rel_path})")
        if loaded > 0:
            logger.info(f"[AiriVoice] 从网页配置加载 {loaded} 个额外语音")

    def _check_admin(self, event: AstrMessageEvent) -> bool:
        if self.admin_mode == "all":
            return True
        if self.admin_mode == "admin":
            if getattr(event, 'is_admin', False) or getattr(event, 'is_master', False):
                return True
            try:
                role = event.get_platform_user_role()
                if role in ('admin', 'owner', 'master'):
                    return True
            except AttributeError:
                pass
            return False
        if self.admin_mode == "whitelist":
            user_id = self._get_user_id(event)
            if user_id and user_id in self.admin_whitelist:
                return True
            uname = getattr(event, 'sender_name', None) or getattr(event, 'nickname', None)
            if uname and uname in self.admin_whitelist:
                return True
            return False
        return False

    def _load_image_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        font_candidates = [
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "msyhbd.ttc" if bold else "msyh.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for font_path in font_candidates:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _fit_text(self, draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        ellipsis = "…"
        trimmed = text
        while trimmed:
            trimmed = trimmed[:-1]
            candidate = trimmed + ellipsis
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                return candidate
        return ellipsis

    def _fill_vertical_gradient(self, img: Image.Image, top_color, bottom_color) -> None:
        width, height = img.size
        draw = ImageDraw.Draw(img)
        if height <= 1:
            draw.rectangle((0, 0, width, height), fill=top_color)
            return
        for y in range(height):
            ratio = y / (height - 1)
            color = tuple(
                int(top_color[index] * (1 - ratio) + bottom_color[index] * ratio)
                for index in range(3)
            )
            draw.line((0, y, width, y), fill=color)

    # ==================== 新增：图片生成方法 ====================
    def _create_voice_list_image(self, page: int = 1) -> Path:
        total = len(self.sorted_keys)
        total_pages = max(1, (total + IMAGE_PAGE_SIZE - 1) // IMAGE_PAGE_SIZE)
        page = max(1, min(page, total_pages))

        start = (page - 1) * IMAGE_PAGE_SIZE
        page_keys = self.sorted_keys[start:start + IMAGE_PAGE_SIZE]

        columns = 2
        padding_x = 64
        card_gap_x = 26
        card_gap_y = 18
        header_height = 160
        footer_height = 92
        card_height = 82
        content_width = IMAGE_WIDTH - padding_x * 2
        card_width = (content_width - card_gap_x) // columns
        rows = max(1, (len(page_keys) + columns - 1) // columns)
        height = header_height + rows * card_height + (rows - 1) * card_gap_y + footer_height

        img = Image.new("RGBA", (IMAGE_WIDTH, height), IMAGE_BG_COLOR_TOP)
        self._fill_vertical_gradient(img, IMAGE_BG_COLOR_TOP, IMAGE_BG_COLOR_BOTTOM)
        draw = ImageDraw.Draw(img)

        accent_colors = [
            (59, 130, 246),
            (20, 184, 166),
            (245, 158, 11),
            (99, 102, 241),
        ]

        draw.ellipse((-120, -100, 360, 380), fill=(59, 130, 246, 28))
        draw.ellipse((IMAGE_WIDTH - 380, 20, IMAGE_WIDTH + 80, 480), fill=(20, 184, 166, 24))

        header_box = (36, 26, IMAGE_WIDTH - 36, 144)
        shadow_box = (header_box[0] + 6, header_box[1] + 8, header_box[2] + 6, header_box[3] + 8)
        draw.rounded_rectangle(shadow_box, radius=32, fill=(0, 0, 0, 20))
        draw.rounded_rectangle(header_box, radius=32, fill=(255, 255, 255, 244), outline=(224, 231, 240, 255), width=2)

        title_font = self._load_image_font(38, bold=True)
        subtitle_font = self._load_image_font(20)
        stat_font = self._load_image_font(22, bold=True)
        footer_font = self._load_image_font(22)
        card_title_font = self._load_image_font(28, bold=True)
        card_hint_font = self._load_image_font(18)
        badge_font = self._load_image_font(18, bold=True)

        title = "AiriVoice 语音列表"
        subtitle = f"第 {page}/{total_pages} 页 · 共 {total} 个语音 · 双列卡片展示"
        draw.text((68, 46), title, font=title_font, fill=(20, 28, 45))
        draw.text((68, 96), subtitle, font=subtitle_font, fill=(92, 102, 121))

        pill_y = 50
        pills = [
            ("总数", str(total), (235, 245, 255), (59, 130, 246)),
            ("页码", f"{page}/{total_pages}", (236, 250, 248), (20, 184, 166)),
        ]
        pill_x = IMAGE_WIDTH - 408
        for label, value, pill_bg, pill_fg in pills:
            pill_width = 156 if label == "总数" else 168
            draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_width, pill_y + 48), radius=24, fill=pill_bg)
            draw.text((pill_x + 16, pill_y + 10), label, font=subtitle_font, fill=(85, 96, 114))
            value_box = draw.textbbox((0, 0), value, font=stat_font)
            value_width = value_box[2] - value_box[0]
            draw.text((pill_x + pill_width - value_width - 16, pill_y + 8), value, font=stat_font, fill=pill_fg)
            pill_x += pill_width + 14

        card_top = 176
        for index, name in enumerate(page_keys):
            row = index // columns
            col = index % columns
            x1 = padding_x + col * (card_width + card_gap_x)
            y1 = card_top + row * (card_height + card_gap_y)
            x2 = x1 + card_width
            y2 = y1 + card_height
            accent = accent_colors[index % len(accent_colors)]

            draw.rounded_rectangle((x1 + 5, y1 + 7, x2 + 5, y2 + 7), radius=24, fill=(0, 0, 0, 18))
            draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(255, 255, 255, 250), outline=(227, 233, 242, 255), width=2)
            draw.rounded_rectangle((x1, y1, x1 + 12, y2), radius=8, fill=accent)

            badge_box = (x1 + 22, y1 + 22, x1 + 58, y1 + 58)
            draw.ellipse(badge_box, fill=(accent[0], accent[1], accent[2], 28), outline=accent, width=2)
            badge_text = f"{start + index + 1:02d}"
            badge_bounds = draw.textbbox((0, 0), badge_text, font=badge_font)
            badge_text_x = badge_box[0] + (badge_box[2] - badge_box[0] - (badge_bounds[2] - badge_bounds[0])) / 2
            badge_text_y = badge_box[1] + (badge_box[3] - badge_box[1] - (badge_bounds[3] - badge_bounds[1])) / 2 - 1
            draw.text((badge_text_x, badge_text_y), badge_text, font=badge_font, fill=accent)

            name_x = x1 + 78
            name_max_width = card_width - 108
            fitted_name = self._fit_text(draw, name, card_title_font, name_max_width)
            draw.text((name_x, y1 + 18), fitted_name, font=card_title_font, fill=IMAGE_TEXT_COLOR)
            draw.text((name_x, y1 + 50), "直接输入关键词即可发送", font=card_hint_font, fill=(102, 113, 132))

        footer_y = height - footer_height + 10
        draw.rounded_rectangle((36, footer_y, IMAGE_WIDTH - 36, height - 18), radius=22, fill=(255, 255, 255, 220), outline=(225, 232, 241, 255), width=1)
        footer_text = "直接输入语音名称即可发送 · /voice.list [页码] 可翻页"
        draw.text((68, footer_y + 18), footer_text, font=footer_font, fill=(93, 103, 121))

        if total_pages > 1:
            nav_parts = []
            if page > 1:
                nav_parts.append(f"上一页 /voice.list {page - 1}")
            if page < total_pages:
                nav_parts.append(f"下一页 /voice.list {page + 1}")
            nav_text = " · ".join(nav_parts)
            nav_box = draw.textbbox((0, 0), nav_text, font=footer_font)
            nav_width = nav_box[2] - nav_box[0]
            draw.text((IMAGE_WIDTH - nav_width - 68, footer_y + 18), nav_text, font=footer_font, fill=(59, 130, 246))

        save_path = self.data_dir / f"voice_list_p{page}.png"
        img.save(save_path)
        return save_path

    # ==================== 指令（仅修改 list 和 help） ====================

    @filter.command("voice.list")
    async def list_voices(self, event: AstrMessageEvent):
        if not self.sorted_keys:
            yield event.plain_result("当前没有可用语音～\n将语音文件放入 voices/ 目录或通过网页上传")
            return

        args = (event.message_str or "").strip().split()
        page = max(1, int(args[1])) if len(args) > 1 and args[1].isdigit() else 1
        total = len(self.sorted_keys)
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

        if self.list_as_image:
            if page > total_pages:
                yield event.plain_result(f"页码过大～总共 {total_pages} 页")
                return
            img_path = self._create_voice_list_image(page)
            yield event.chain_result([AstrImage.fromFileSystem(str(img_path))])
        else:
            if page > total_pages:
                yield event.plain_result(f"页码过大～总共 {total_pages} 页")
                return
            start = (page - 1) * PAGE_SIZE
            page_keys = self.sorted_keys[start:start + PAGE_SIZE]

            msg = f"📋 可用语音（第 {page}/{total_pages} 页，共 {total} 个）：\n\n"
            msg += "\n".join(f"• {k}" for k in page_keys)
            if total_pages > 1:
                nav = []
                if page > 1:
                    nav.append(f"/voice.list {page-1} ← 上一页")
                if page < total_pages:
                    nav.append(f"/voice.list {page+1} → 下一页")
                msg += "\n\n" + " | ".join(nav)
            yield event.plain_result(msg)

    @filter.command("voice.help")
    async def help(self, event: AstrMessageEvent):
        is_admin = self._check_admin(event)
        commands = [
            "📋 /voice.list [页码] - 查看可用语音列表",
            "🎲 随机语音 或 随机发条语音 - 随机发送一条语音",
            "🎲 随机 关键词 - 在包含关键词的语音中随机发送",
            "❓ /voice.help - 显示此帮助",
        ]
        if is_admin:
            commands.extend([
                "➕ /voice.add 名字 - 引用语音消息添加新语音",
                "🗑️ /voice.delete 名字 - 删除通过 .add 添加的语音",
                "🔄 /voice.reload - 重新加载语音列表",
                "🔐 /voice.check - 查看当前用户权限",
            ])

        help_msg = f"""🌸 **AiriVoice 语音插件 v2.4**

【核心功能】
• 直接输入语音关键词即可发送对应语音
• 支持本地 voices/ 文件夹、网页后台上传、/voice.add 三种添加方式

【触发模式】
🔹 direct（默认）：直接输入关键词
🔹 prefix：需使用 #voice 关键词
🔹 llm：由大模型通过工具调用

【可用命令】
{chr(10).join(commands)}

【图片列表】
可在插件配置中开启 list_as_image，让 /voice.list 以图片形式展示（更清晰）
"""
        yield event.plain_result(help_msg)

    # ==================== 以下所有方法完全保持不变 ====================

    @filter.regex(r"^\s*.+\s*$")
    async def voice_handler(self, event: AstrMessageEvent):
        # ... 你原来的完整代码（未做任何修改）
        text = (event.message_str or "").strip()
        if not text:
            return
        current_pool_len = len(self.config.get("extra_voice_pool", []))
        if current_pool_len > self.last_pool_len:
            logger.info("[AiriVoice] 检测到网页配置变化，自动刷新语音列表")
            self._load_web_voices(self.config)
            self._update_sorted_keys()
            self.last_pool_len = current_pool_len

        # 随机语音处理...
        if text.startswith("随机") and self.voice_map:
            if text in {"随机发条语音", "随机语音"}:
                name = random.choice(list(self.voice_map.keys()))
                matched_path = self.voice_map.get(name)
                if matched_path:
                    try:
                        yield event.chain_result([Record.fromFileSystem(matched_path)])
                        logger.debug(f"[AiriVoice] 随机发送语音（全局）：'{name}'")
                    except Exception as e:
                        logger.error(f"[AiriVoice] 随机发送失败 '{name}': {e}")
                        yield event.plain_result("语音发送失败")
                else:
                    yield event.plain_result("当前没有可用语音～")
                return

            m = re.match(r"^随机\s*(.+)$", text)
            if m:
                kw = m.group(1).strip()
                candidates = [name for name in self.voice_map.keys() if kw in name]
                if not candidates:
                    yield event.plain_result(f"未找到包含「{kw}」的语音")
                    return
                name = random.choice(candidates)
                matched_path = self.voice_map.get(name)
                if matched_path:
                    try:
                        yield event.chain_result([Record.fromFileSystem(matched_path)])
                    except Exception as e:
                        logger.error(f"[AiriVoice] 随机发送失败 '{name}': {e}")
                        yield event.plain_result("语音发送失败")
                return

        # 普通关键词处理...
        keyword = text
        if self.trigger_mode == "prefix":
            match = re.search(r"^#voice\s+(.+)", text, re.I)
            if not match:
                return
            keyword = match.group(1).strip()

        matched_path = self.voice_map.get(keyword)
        if matched_path:
            try:
                yield event.chain_result([Record.fromFileSystem(matched_path)])
                logger.debug(f"[AiriVoice] 发送语音：'{keyword}'")
            except FileNotFoundError as e:
                logger.error(f"[AiriVoice] 文件不存在 '{keyword}': {e}")
                yield event.plain_result("语音文件不存在")
            except Exception as e:
                logger.error(f"[AiriVoice] 发送失败 '{keyword}': {e}")
                yield event.plain_result("语音发送失败")

    @filter.command("voice.add")
    async def voice_add(self, event: AstrMessageEvent, name: str):
        if not self._check_admin(event):
            yield event.plain_result("❌ 权限不足：此命令仅限管理员使用")
            return
        if not self._get_reply_id(event):
            yield event.plain_result("❌ 请引用一条语音消息后再使用此命令")
            return
        if not name or name.strip() == "":
            yield event.plain_result("❌ 请提供语音名称，例如：/voice.add 打卡啦摩托")
            return
        name = name.strip()
        if name in self.voice_map:
            yield event.plain_result(f"⚠️ 语音「{name}」已存在，如需覆盖请先删除旧语音")
            return
        audio_url = await self._get_audio_url(event)
        if not audio_url:
            yield event.plain_result("❌ 未能从引用的消息中提取到音频，请确保引用的是语音消息")
            return
        logger.debug(f"[AiriVoice] 获取到音频 URL: {audio_url}")
        audio_data = await self._download_audio(audio_url)
        if not audio_data:
            yield event.plain_result("❌ 音频下载失败，请稍后重试")
            return
        ext = self._get_file_ext_from_url(audio_url)
        file_path = self.user_added_dir / f"{name}{ext}"
        try:
            with open(file_path, "wb") as f:
                f.write(audio_data)
            self.voice_map[name] = str(file_path)
            self._update_sorted_keys()
            yield event.plain_result(f"✅ 语音「{name}」添加成功！\n📁 文件：{name}{ext}\n💾 大小：{len(audio_data) / 1024:.2f} KB")
        except Exception as e:
            logger.error(f"[AiriVoice] 保存语音失败：{e}")
            yield event.plain_result(f"❌ 保存语音失败：{str(e)}")

    @filter.command("voice.delete")
    async def voice_delete(self, event: AstrMessageEvent, name: str):
        if not self._check_admin(event):
            yield event.plain_result("❌ 权限不足：此命令仅限管理员使用")
            return
        if name not in self.voice_map:
            yield event.plain_result(f"❌ 语音「{name}」不存在")
            return
        file_path = Path(self.voice_map[name])
        if not str(file_path.resolve()).startswith(str(self.user_added_dir.resolve())):
            yield event.plain_result(f"⚠️ 只能删除通过 /voice.add 添加的语音，本地 voices/ 和网页上传的文件请手动管理")
            return
        try:
            file_path.unlink()
            del self.voice_map[name]
            self._update_sorted_keys()
            yield event.plain_result(f"✅ 语音「{name}」已删除")
        except Exception as e:
            logger.error(f"[AiriVoice] 删除语音失败：{e}")
            yield event.plain_result(f"❌ 删除失败：{str(e)}")

    @filter.command("voice.reload")
    async def reload_voices(self, event: AstrMessageEvent):
        if not self._check_admin(event):
            yield event.plain_result("❌ 权限不足：此命令仅限管理员使用")
            return
        self._load_local_voices()
        self._load_web_voices(self.config)
        self._update_sorted_keys()
        self.last_pool_len = len(self.config.get("extra_voice_pool", []))
        yield event.plain_result(f"✅ 已重新加载，共 {len(self.voice_map)} 个语音")

    @filter.command("voice.check")
    async def check_permission(self, event: AstrMessageEvent):
        is_admin = self._check_admin(event)
        user_id = self._get_user_id(event) or "未知"
        msg = f"🔐 权限检查\n\n"
        msg += f"用户 ID: {user_id}\n"
        msg += f"权限模式：{self.admin_mode}\n"
        msg += f"是否有权限：{'✅ 是' if is_admin else '❌ 否'}\n"
        if self.admin_mode == "whitelist" and not is_admin:
            msg += f"\n💡 提示：在 AstrBot 网页后台 → 插件配置 → admin_whitelist 中添加您的用户 ID"
        yield event.plain_result(msg)

    # ────────────────────────────────────────────────
    # 新功能：bot 回复自动追加语音（核心部分）
    # ────────────────────────────────────────────────

    @filter.on_decorating_result()
    async def on_bot_reply_auto_voice(self, event: AstrMessageEvent):
        if not self.auto_reply_voice_enabled:
            return

        result = event.get_result()
        if not result or not hasattr(result, "chain") or not result.chain:
            return

        text_parts = []
        has_record_already = False
        for seg in result.chain:
            if isinstance(seg, Record):
                has_record_already = True
            elif hasattr(seg, "text"):
                text_parts.append(str(getattr(seg, "text", "") or ""))
            elif isinstance(seg, str):
                text_parts.append(seg)

        text = "".join(text_parts).strip()
        if not text or has_record_already:
            return  # 已包含语音或无文本 → 不处理

        # 新增：过滤插件自己的命令回复，避免自我触发
        if "可用语音" in text or "第" in text and "页" in text or "/voice.list" in text:
            logger.debug("[AiriVoice-auto] 检测到 /voice.list 回复，跳过自动追加语音")
            return

        logger.debug(f"[AiriVoice-auto] bot 回复文本待检查: {text!r}")

        for keyword in self.sorted_keys:
            if keyword in text:
                path = self.voice_map.get(keyword)
                if path:
                    try:
                        result.chain.append(Record.fromFileSystem(path))
                        logger.info(
                            f"[AiriVoice-auto] 已追加语音 → 关键词: '{keyword}'  文件: {path}"
                        )
                        break  # 只追加一个，避免刷屏
                    except Exception as e:
                        logger.error(f"[AiriVoice-auto] 追加语音失败 '{keyword}': {e}")
