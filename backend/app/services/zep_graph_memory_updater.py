"""
Zep图谱记忆更新服务
将模拟中的Agent活动动态更新到Zep图谱中
"""

import os
import time
import threading
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from .graphiti_client import Zep

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """Agent活动记录"""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str
    
    def to_episode_text(self) -> str:
        """
        将活动转换为可以发送给Zep的文本描述
        
        采用自然语言描述格式，让Zep能够从中提取实体和关系
        不添加模拟相关的前缀，避免误导图谱更新
        """
        # 根据不同的动作类型生成不同的描述
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }
        
        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()
        
        # 直接返回 "agent名称: 活动描述" 格式，不添加模拟前缀
        return f"{self.agent_name}: {description}"
    
    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"发布了一条帖子：「{content}」"
        return "发布了一条帖子"
    
    def _describe_like_post(self) -> str:
        """点赞帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"点赞了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"点赞了一条帖子：「{post_content}」"
        elif post_author:
            return f"点赞了{post_author}的一条帖子"
        return "点赞了一条帖子"
    
    def _describe_dislike_post(self) -> str:
        """踩帖子 - 包含帖子原文和作者信息"""
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if post_content and post_author:
            return f"踩了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"踩了一条帖子：「{post_content}」"
        elif post_author:
            return f"踩了{post_author}的一条帖子"
        return "踩了一条帖子"
    
    def _describe_repost(self) -> str:
        """转发帖子 - 包含原帖内容和作者信息"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        
        if original_content and original_author:
            return f"转发了{original_author}的帖子：「{original_content}」"
        elif original_content:
            return f"转发了一条帖子：「{original_content}」"
        elif original_author:
            return f"转发了{original_author}的一条帖子"
        return "转发了一条帖子"
    
    def _describe_quote_post(self) -> str:
        """引用帖子 - 包含原帖内容、作者信息和引用评论"""
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        
        base = ""
        if original_content and original_author:
            base = f"引用了{original_author}的帖子「{original_content}」"
        elif original_content:
            base = f"引用了一条帖子「{original_content}」"
        elif original_author:
            base = f"引用了{original_author}的一条帖子"
        else:
            base = "引用了一条帖子"
        
        if quote_content:
            base += f"，并评论道：「{quote_content}」"
        return base
    
    def _describe_follow(self) -> str:
        """关注用户 - 包含被关注用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"关注了用户「{target_user_name}」"
        return "关注了一个用户"
    
    def _describe_create_comment(self) -> str:
        """发表评论 - 包含评论内容和所评论的帖子信息"""
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        
        if content:
            if post_content and post_author:
                return f"在{post_author}的帖子「{post_content}」下评论道：「{content}」"
            elif post_content:
                return f"在帖子「{post_content}」下评论道：「{content}」"
            elif post_author:
                return f"在{post_author}的帖子下评论道：「{content}」"
            return f"评论道：「{content}」"
        return "发表了评论"
    
    def _describe_like_comment(self) -> str:
        """点赞评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"点赞了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"点赞了一条评论：「{comment_content}」"
        elif comment_author:
            return f"点赞了{comment_author}的一条评论"
        return "点赞了一条评论"
    
    def _describe_dislike_comment(self) -> str:
        """踩评论 - 包含评论内容和作者信息"""
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        
        if comment_content and comment_author:
            return f"踩了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"踩了一条评论：「{comment_content}」"
        elif comment_author:
            return f"踩了{comment_author}的一条评论"
        return "踩了一条评论"
    
    def _describe_search(self) -> str:
        """搜索帖子 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"搜索了「{query}」" if query else "进行了搜索"
    
    def _describe_search_user(self) -> str:
        """搜索用户 - 包含搜索关键词"""
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"搜索了用户「{query}」" if query else "搜索了用户"
    
    def _describe_mute(self) -> str:
        """屏蔽用户 - 包含被屏蔽用户的名称"""
        target_user_name = self.action_args.get("target_user_name", "")
        
        if target_user_name:
            return f"屏蔽了用户「{target_user_name}」"
        return "屏蔽了一个用户"
    
    def _describe_generic(self) -> str:
        # 对于未知的动作类型，生成通用描述
        return f"执行了{self.action_type}操作"


class ZepGraphMemoryUpdater:
    """
    Zep图谱记忆更新器
    
    监控模拟的actions日志文件，将新的agent活动实时更新到Zep图谱中。
    按平台分组，每累积BATCH_SIZE条活动后批量发送到Zep。
    
    所有有意义的行为都会被更新到Zep，action_args中会包含完整的上下文信息：
    - 点赞/踩的帖子原文
    - 转发/引用的帖子原文
    - 关注/屏蔽的用户名
    - 点赞/踩的评论原文
    """
    
    # 批量发送大小（每个平台累积多少条后发送）
    BATCH_SIZE = 5
    
    # 平台名称映射（用于控制台显示）
    PLATFORM_DISPLAY_NAMES = {
        'twitter': '世界1',
        'reddit': '世界2',
    }
    
    # 发送间隔（秒），避免请求过快
    SEND_INTERVAL = 0.5
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    # EXECPLAN2 F-4-5: 批次最终失败后，重新缓冲等待下一次发送时的硬上限（防止内存无界增长）。
    MAX_BUFFERED_RETRY = 500

    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        """
        初始化更新器
        
        Args:
            graph_id: Zep图谱ID
            api_key: Zep API Key（可选，默认从配置读取）
        """
        self.graph_id = graph_id
        self.api_key = api_key or Config.ZEP_API_KEY
        
        if not self.api_key:
            raise ValueError("ZEP_API_KEY未配置")
        
        self.client = Zep(api_key=self.api_key)
        
        # 活动队列
        self._activity_queue: Queue = Queue()
        
        # 按平台分组的活动缓冲区（每个平台各自累积到BATCH_SIZE后批量发送）
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()
        
        # 控制标志
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # 统计
        self._total_activities = 0  # 实际添加到队列的活动数
        self._total_sent = 0        # 成功发送到Zep的批次数
        self._total_items_sent = 0  # 成功发送到Zep的活动条数
        self._failed_count = 0      # 发送失败的批次数
        self._failed_items = 0      # EXECPLAN2 F-4-5: 发送失败的活动条数（量化丢失，而非仅批次数）
        self._dead_lettered = 0     # EXECPLAN2 F-4-5: 关停时写入死信文件的活动条数
        self._skipped_count = 0     # 被过滤跳过的活动数（DO_NOTHING）

        # EXECPLAN2 F-4-5: 关停时若批次仍发送失败，缓冲区会被 _flush_remaining 清空，
        # 无法靠重新缓冲恢复；改为追加到 sim-scoped 死信 JSONL，便于事后回放。
        self._dead_letter_path = os.path.join(
            Config.OASIS_SIMULATION_DATA_DIR,
            "_zep_dead_letter",
            f"{graph_id}.jsonl",
        )

        logger.info(f"ZepGraphMemoryUpdater 初始化完成: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")
    
    def _get_platform_display_name(self, platform: str) -> str:
        """获取平台的显示名称"""
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)
    
    def start(self):
        """启动后台工作线程"""
        if self._running:
            return
        
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ZepMemoryUpdater-{self.graph_id[:8]}"
        )
        self._worker_thread.start()
        logger.info(f"ZepGraphMemoryUpdater 已启动: graph_id={self.graph_id}")
    
    def stop(self):
        """停止后台工作线程"""
        self._running = False
        
        # 发送剩余的活动
        self._flush_remaining()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)
        
        logger.info(f"ZepGraphMemoryUpdater 已停止: graph_id={self.graph_id}, "
                   f"total_activities={self._total_activities}, "
                   f"batches_sent={self._total_sent}, "
                   f"items_sent={self._total_items_sent}, "
                   f"failed_batches={self._failed_count}, "
                   f"failed_items={self._failed_items}, "  # EXECPLAN2 F-4-5: 量化丢失的活动条数
                   f"dead_lettered={self._dead_lettered}, "  # EXECPLAN2 F-4-5: 写入死信文件的条数
                   f"skipped={self._skipped_count}")
    
    def add_activity(self, activity: AgentActivity):
        """
        添加一个agent活动到队列
        
        所有有意义的行为都会被添加到队列，包括：
        - CREATE_POST（发帖）
        - CREATE_COMMENT（评论）
        - QUOTE_POST（引用帖子）
        - SEARCH_POSTS（搜索帖子）
        - SEARCH_USER（搜索用户）
        - LIKE_POST/DISLIKE_POST（点赞/踩帖子）
        - REPOST（转发）
        - FOLLOW（关注）
        - MUTE（屏蔽）
        - LIKE_COMMENT/DISLIKE_COMMENT（点赞/踩评论）
        
        action_args中会包含完整的上下文信息（如帖子原文、用户名等）。
        
        Args:
            activity: Agent活动记录
        """
        # 跳过DO_NOTHING类型的活动
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        
        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"添加活动到Zep队列: {activity.agent_name} - {activity.action_type}")
    
    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        """
        从字典数据添加活动
        
        Args:
            data: 从actions.jsonl解析的字典数据
            platform: 平台名称 (twitter/reddit)
        """
        # 跳过事件类型的条目
        if "event_type" in data:
            return
        
        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        
        self.add_activity(activity)
    
    def _worker_loop(self):
        """后台工作循环 - 按平台批量发送活动到Zep"""
        while self._running or not self._activity_queue.empty():
            try:
                # 尝试从队列获取活动（超时1秒）
                try:
                    activity = self._activity_queue.get(timeout=1)
                    
                    # 将活动添加到对应平台的缓冲区
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        
                        # 检查该平台是否达到批量大小
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            # 释放锁后再发送
                            self._send_batch_activities(batch, platform)
                            # 发送间隔，避免请求过快
                            time.sleep(self.SEND_INTERVAL)
                    
                except Empty:
                    pass
                    
            except Exception as e:
                logger.error(f"工作循环异常: {e}")
                time.sleep(1)
    
    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """
        批量发送活动到Zep图谱（合并为一条文本）
        
        Args:
            activities: Agent活动列表
            platform: 平台名称
        """
        if not activities:
            return
        
        # 将多条活动合并为一条文本，用换行分隔
        episode_texts = [activity.to_episode_text() for activity in activities]
        combined_text = "\n".join(episode_texts)
        
        # 带重试的发送
        for attempt in range(self.MAX_RETRIES):
            try:
                self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text
                )
                
                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(f"成功批量发送 {len(activities)} 条{display_name}活动到图谱 {self.graph_id}")
                logger.debug(f"批量内容预览: {combined_text[:200]}...")
                # T3.10: 除自由文本 episode 外，再为带「作者+目标」的动作写带名 typed 边，
                # 让身份与轮级双时态在反馈回路中存活（gate: SIM_TYPED_FEEDBACK_EDGES）。
                self._write_typed_edges(activities)
                return
                
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"批量发送到Zep失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量发送到Zep失败，已重试{self.MAX_RETRIES}次: {e}")
                    self._failed_count += 1
                    # EXECPLAN2 F-4-5: 不再静默丢弃整批活动——尽力恢复并量化丢失。
                    self._failed_items += len(activities)
                    self._recover_failed_batch(activities, platform)
    
    def _recover_failed_batch(self, activities: List[AgentActivity], platform: str):
        """EXECPLAN2 F-4-5: 批次最终失败后的恢复路径（best-effort，绝不抛出）。

        调用约定：本方法的两处上游调用（_worker_loop 与 _flush_remaining）在调用
        _send_batch_activities 时都已持有 self._buffer_lock，而 threading.Lock 不可重入，
        因此这里 **不得** 再次获取 self._buffer_lock——直接在持锁上下文中操作缓冲区。

        - 运行期（self._running=True）：把失败活动重新缓冲，受 MAX_BUFFERED_RETRY 硬上限约束，
          等待下一次 BATCH_SIZE 触发或最终 flush 重发，可从短暂的 FalkorDB/InternalServerError
          窗口中恢复。
        - 关停期（self._running=False，即 _flush_remaining 调用栈）：缓冲区随后会被 _flush_remaining
          清空，重新缓冲无意义，改为追加写入 sim-scoped 死信 JSONL 以便事后回放。
        """
        try:
            if self._running:
                # 上游已持锁；直接修改缓冲区，切勿再次获取 _buffer_lock（不可重入会死锁）。
                buf = self._platform_buffers.setdefault(platform, [])
                room = self.MAX_BUFFERED_RETRY - len(buf)
                if room > 0:
                    recovered = activities[:room]
                    buf.extend(recovered)
                    dropped = len(activities) - len(recovered)
                else:
                    dropped = len(activities)
                if dropped > 0:
                    # 超过缓冲上限的部分仍会丢失，写入死信文件以免静默。
                    self._write_dead_letter(activities[len(activities) - dropped:], platform)
            else:
                # 关停路径：直接写死信文件。
                self._write_dead_letter(activities, platform)
        except Exception as e:  # noqa: BLE001  恢复本身是增强项，绝不破坏主流程
            logger.error(f"失败批次恢复异常（{len(activities)} 条活动可能丢失）: {e}")

    def _write_dead_letter(self, activities: List[AgentActivity], platform: str):
        """EXECPLAN2 F-4-5: 将无法恢复的活动追加到死信 JSONL，便于回放（best-effort）。"""
        if not activities:
            return
        try:
            os.makedirs(os.path.dirname(self._dead_letter_path), exist_ok=True)
            now = datetime.now().isoformat()
            lines = []
            for act in activities:
                record = {
                    "graph_id": self.graph_id,
                    "platform": platform,
                    "dead_lettered_at": now,
                    "combined_text": act.to_episode_text(),
                    "agent_name": act.agent_name,
                    "action_type": act.action_type,
                    "round": act.round_num,
                    "timestamp": act.timestamp,
                }
                lines.append(json.dumps(record, ensure_ascii=False))
            # 死信是追加语义（非整文件重写），直接以 append 模式落盘。
            with open(self._dead_letter_path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._dead_lettered += len(activities)
            logger.warning(
                f"已将 {len(activities)} 条无法发送的活动写入死信文件: {self._dead_letter_path}"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"写入死信文件失败（{len(activities)} 条活动丢失）: {e}")

    # T3.10: 动作 → (typed 边名, 目标名候选 action_args 键)。用于把交互写成带名实体边。
    _TYPED_EDGE_MAP = {
        "LIKE_POST": ("LIKED", ("post_author_name",)),
        "DISLIKE_POST": ("DISLIKED", ("post_author_name",)),
        "REPOST": ("REPOSTED", ("original_author_name",)),
        "QUOTE_POST": ("QUOTED", ("original_author_name", "quoted_author_name")),
        "CREATE_COMMENT": ("REPLIED_TO", ("post_author_name",)),
        "LIKE_COMMENT": ("LIKED", ("comment_author_name", "post_author_name")),
        "DISLIKE_COMMENT": ("DISLIKED", ("comment_author_name", "post_author_name")),
        # EXECPLAN2 F-4-0: 模拟器在 _enrich_action_context 中只把 FOLLOW/MUTE 的目标写入
        # action_args['target_user_name']（canonical key，与 _describe_follow/_describe_mute 一致）。
        # 因此必须把 target_user_name 放在候选键首位，否则 FOLLOWED/MUTED typed 边永不写入。
        # 其余键作为无害回退保留。
        "FOLLOW": ("FOLLOWED", ("target_user_name", "followee_name", "target_name", "followee")),
        "MUTE": ("MUTED", ("target_user_name", "target_name", "mutee_name")),
    }

    def _write_typed_edges(self, activities: List[AgentActivity]):
        """为带「作者+目标」的动作写带名 typed 边（best-effort；gate: SIM_TYPED_FEEDBACK_EDGES）。"""
        if not getattr(Config, "SIM_TYPED_FEEDBACK_EDGES", False):
            return
        for act in activities:
            spec = self._TYPED_EDGE_MAP.get(act.action_type)
            if not spec:
                continue
            edge_name, keys = spec
            target = ""
            for k in keys:
                v = str((act.action_args or {}).get(k, "") or "").strip()
                if v:
                    target = v
                    break
            author = (act.agent_name or "").strip()
            if not author or not target or author == target:
                continue
            valid_at = None
            try:
                from datetime import datetime
                if act.timestamp:
                    valid_at = datetime.fromisoformat(act.timestamp)
            except Exception:
                valid_at = None
            try:
                self.client.graph.add_triplet(
                    self.graph_id, author, edge_name, target,
                    f"{author} {edge_name} {target} (round {act.round_num})",
                    valid_at=valid_at,
                )
            except Exception as e:  # typed edges are an enhancement; never break the loop
                logger.debug(f"typed feedback edge skipped ({author}-{edge_name}-{target}): {e}")

    def write_interview_fact(self, agent_name: str, statement: str, valid_at=None, *,
                             feedback_allowed: Optional[bool] = None) -> bool:
        """T3.14: 把一条采访回答写为 typed 图谱事实

        ``<agent> STATED_AT_END_OF_SIM 模拟终局陈述`` (fact=回答全文)，让最丰富的收尾反思变成
        可检索的持久事实，而非被摘要后丢失。key-free（走本地 shim）。best-effort，失败返回 False。

        Foglamp WP1 (1A, I-11)：采访是模拟产物。默认门 SIM_INTERVIEW_GRAPH_FEEDBACK=false
        拒绝写入观察图——合成的终局反思不得变成可检索「事实」。采访全文仍保留在 run 产物里。

        FU-8：``feedback_allowed`` 是调用方按该运行钉住的安全政策解析出的门
        （zep_tools.interview_agents 传入）；None → 环境值 Config.SIM_INTERVIEW_GRAPH_FEEDBACK（旧行为）。
        """
        allowed = (getattr(Config, "SIM_INTERVIEW_GRAPH_FEEDBACK", False)
                   if feedback_allowed is None else feedback_allowed)
        if not allowed:
            logger.debug("采访事实写入被 SIM_INTERVIEW_GRAPH_FEEDBACK=false 拒绝（Foglamp 1A/I-11）")
            return False
        agent_name = (agent_name or "").strip()
        statement = (statement or "").strip()
        if not agent_name or not statement:
            return False
        try:
            self.client.graph.add_triplet(
                self.graph_id,
                agent_name,
                "STATED_AT_END_OF_SIM",
                "模拟终局陈述",
                f"{agent_name}: {statement[:1500]}",
                valid_at=valid_at,
                source_label="Entity",
                target_label="Entity",
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"采访事实写入跳过 ({agent_name}): {e}")
            return False

    def _flush_remaining(self):
        """发送队列和缓冲区中剩余的活动"""
        # 首先处理队列中剩余的活动，添加到缓冲区
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break
        
        # 然后发送各平台缓冲区中剩余的活动（即使不足BATCH_SIZE条）
        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"发送{display_name}平台剩余的 {len(buffer)} 条活动")
                    self._send_batch_activities(buffer, platform)
            # 清空所有缓冲区
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,  # 添加到队列的活动总数
            "batches_sent": self._total_sent,            # 成功发送的批次数
            "items_sent": self._total_items_sent,        # 成功发送的活动条数
            "failed_count": self._failed_count,          # 发送失败的批次数
            "failed_items": self._failed_items,          # EXECPLAN2 F-4-5: 发送失败的活动条数
            "dead_lettered": self._dead_lettered,        # EXECPLAN2 F-4-5: 写入死信文件的活动条数
            "skipped_count": self._skipped_count,        # 被过滤跳过的活动数（DO_NOTHING）
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,                # 各平台缓冲区大小
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """
    管理多个模拟的Zep图谱记忆更新器
    
    每个模拟可以有自己的更新器实例
    """
    
    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        """
        为模拟创建图谱记忆更新器
        
        Args:
            simulation_id: 模拟ID
            graph_id: Zep图谱ID
            
        Returns:
            ZepGraphMemoryUpdater实例
        """
        with cls._lock:
            # 如果已存在，先停止旧的
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            
            updater = ZepGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            
            logger.info(f"创建图谱记忆更新器: simulation_id={simulation_id}, graph_id={graph_id}")
            return updater
    
    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        """获取模拟的更新器"""
        return cls._updaters.get(simulation_id)
    
    @classmethod
    def stop_updater(cls, simulation_id: str):
        """停止并移除模拟的更新器"""
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"已停止图谱记忆更新器: simulation_id={simulation_id}")
    
    # 防止 stop_all 重复调用的标志
    _stop_all_done = False
    
    @classmethod
    def stop_all(cls):
        """停止所有更新器"""
        # 防止重复调用
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        
        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"停止更新器失败: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("已停止所有图谱记忆更新器")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有更新器的统计信息"""
        return {
            sim_id: updater.get_stats() 
            for sim_id, updater in cls._updaters.items()
        }
