import re
import json
from datetime import datetime
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


class BookkeepingPlugin(Star):
    """记账插件 - 为每个用户独立管理账单"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.plugin_name = "astrbot_plugin_bookkeeping"
        self.data_path = get_astrbot_data_path() / "plugin_data" / self.plugin_name
        self.data_path.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """插件初始化方法"""
        logger.info(f"记账插件已启动，数据路径: {self.data_path}")

    def _get_user_file(self, user_name: str) -> Path:
        """获取用户的账单文件路径"""
        return self.data_path / f"{user_name}_bookkeeping.json"

    async def _get_ai_evaluation(
        self, user_name: str, analysis_data: str, umo
    ) -> str:
        """获取 AI 评价。如果 LLM 不可用，返回空字符串"""
        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            prompt = (
                "你是一个专业的财务顾问。请根据下面的账单数据，提供简明的财务评价和建议。"
                "评价要点：1)支出/收入结构 2)消费习惯 3)财务建议。回复要简洁（3-5句话）。\n\n"
                f"{analysis_data}"
            )

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )

            return f"\n\n{'=' * 40}\n{llm_resp.completion_text}"

        except Exception as e:
            logger.debug(f"调用LLM失败: {e}")
            return ""

    @filter.command("记账支出")
    async def record_expense(self, event: AstrMessageEvent):
        """记录支出: 记账支出 <类别> <金额>

        例子: 记账支出 猪肉 15
        """
        user_name = event.get_sender_name()
        message = event.message_str.strip()

        match = re.search(
            r"记账支出[\s\n]+(.+?)[\s\n]+(\d+(?:\.\d{1,2})?)", message
        )

        if not match:
            yield event.plain_result("❌ 格式错误！用法: 记账支出 <类别> <金额>")
            return

        category = match.group(1).strip()
        amount = float(match.group(2))

        await self._save_record(user_name, "expense", category, amount)
        yield event.plain_result(
            f"✅ 记账成功！\n"
            f"类型: 支出\n"
            f"类别: {category}\n"
            f"金额: ¥{amount:.2f}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @filter.command("记账收入")
    async def record_income(self, event: AstrMessageEvent):
        """记录收入: 记账收入 <类别> <金额>

        例子: 记账收入 工资 50
        """
        user_name = event.get_sender_name()
        message = event.message_str.strip()

        match = re.search(
            r"记账收入[\s\n]+(.+?)[\s\n]+(\d+(?:\.\d{1,2})?)", message
        )

        if not match:
            yield event.plain_result("❌ 格式错误！用法: 记账收入 <类别> <金额>")
            return

        category = match.group(1).strip()
        amount = float(match.group(2))

        await self._save_record(user_name, "income", category, amount)
        yield event.plain_result(
            f"✅ 记账成功！\n"
            f"类型: 收入\n"
            f"类别: {category}\n"
            f"金额: ¥{amount:.2f}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @filter.command("查账统计")
    async def query_summary(self, event: AstrMessageEvent):
        """查看个人账户全量统计"""
        user_name = event.get_sender_name()
        records = self._load_records(user_name)

        if not records:
            yield event.plain_result("📊 您还没有记账数据")
            return

        total_income = sum(r["amount"] for r in records if r["type"] == "income")
        total_expense = sum(r["amount"] for r in records if r["type"] == "expense")
        balance = total_income - total_expense

        summary = (
            f"📊 {user_name} 的账户统计\n"
            f"总收入: ¥{total_income:.2f}\n"
            f"总支出: ¥{total_expense:.2f}\n"
            f"余额: ¥{balance:.2f}\n"
            f"记录数: {len(records)}"
        )

        # 获取 AI 评价
        analysis_data = (
            f"用户账户统计数据：\n"
            f"总收入: ¥{total_income:.2f}\n"
            f"总支出: ¥{total_expense:.2f}\n"
            f"余额: ¥{balance:.2f}\n"
            f"记录数: {len(records)}"
        )
        ai_eval = await self._get_ai_evaluation(
            user_name, analysis_data, event.unified_msg_origin
        )

        yield event.plain_result(summary + ai_eval)

    @filter.command("日统计")
    async def query_daily_summary(self, event: AstrMessageEvent):
        """查看今日统计。用法: 日统计 或 日统计 2024-02-25"""
        user_name = event.get_sender_name()
        message = event.message_str.strip()

        match = re.search(r"日统计[\s\n]*(\d{4}-\d{2}-\d{2})?", message)
        if match and match.group(1):
            date_str = match.group(1)
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        records = self._load_records(user_name)

        day_records = [r for r in records if r["time"].startswith(date_str)]

        if not day_records:
            yield event.plain_result(f"📅 {date_str} 没有记账数据")
            return

        daily_income = sum(
            r["amount"] for r in day_records if r["type"] == "income"
        )
        daily_expense = sum(
            r["amount"] for r in day_records if r["type"] == "expense"
        )
        balance = daily_income - daily_expense

        summary = (
            f"📅 {user_name} 的 {date_str} 统计\n"
            f"收入: ¥{daily_income:.2f}\n"
            f"支出: ¥{daily_expense:.2f}\n"
            f"结余: ¥{balance:.2f}\n"
            f"记录数: {len(day_records)}"
        )

        # 获取 AI 评价
        analysis_data = (
            f"用户 {date_str} 日统计数据：\n"
            f"收入: ¥{daily_income:.2f}\n"
            f"支出: ¥{daily_expense:.2f}\n"
            f"结余: ¥{balance:.2f}\n"
            f"记录数: {len(day_records)}"
        )
        ai_eval = await self._get_ai_evaluation(
            user_name, analysis_data, event.unified_msg_origin
        )

        yield event.plain_result(summary + ai_eval)

    @filter.command("月统计")
    async def query_monthly_summary(self, event: AstrMessageEvent):
        """查看月度统计。用法: 月统计 或 月统计 2024-02"""
        user_name = event.get_sender_name()
        message = event.message_str.strip()

        match = re.search(r"月统计[\s\n]*(\d{4}-\d{2})?", message)
        if match and match.group(1):
            month_str = match.group(1)
        else:
            month_str = datetime.now().strftime("%Y-%m")

        records = self._load_records(user_name)

        month_records = [r for r in records if r["time"].startswith(month_str)]

        if not month_records:
            yield event.plain_result(f"📆 {month_str} 没有记账数据")
            return

        monthly_income = sum(
            r["amount"] for r in month_records if r["type"] == "income"
        )
        monthly_expense = sum(
            r["amount"] for r in month_records if r["type"] == "expense"
        )
        balance = monthly_income - monthly_expense

        summary = (
            f"📆 {user_name} 的 {month_str} 统计\n"
            f"收入: ¥{monthly_income:.2f}\n"
            f"支出: ¥{monthly_expense:.2f}\n"
            f"结余: ¥{balance:.2f}\n"
            f"记录数: {len(month_records)}"
        )

        # 获取 AI 评价
        analysis_data = (
            f"用户 {month_str} 月统计数据：\n"
            f"收入: ¥{monthly_income:.2f}\n"
            f"支出: ¥{monthly_expense:.2f}\n"
            f"结余: ¥{balance:.2f}\n"
            f"记录数: {len(month_records)}"
        )
        ai_eval = await self._get_ai_evaluation(
            user_name, analysis_data, event.unified_msg_origin
        )

        yield event.plain_result(summary + ai_eval)

    @filter.command("查账详情")
    async def query_details(self, event: AstrMessageEvent):
        """查看账户详细记录"""
        user_name = event.get_sender_name()
        records = self._load_records(user_name)

        if not records:
            yield event.plain_result("📋 您还没有记账数据")
            return

        records = sorted(records, key=lambda x: x["timestamp"], reverse=True)

        details = f"📋 {user_name} 的账户详情\n" + "=" * 40 + "\n"
        for idx, record in enumerate(records[-20:], 1):
            record_type = "📈 收入" if record["type"] == "income" else "📉 支出"
            details += (
                f"{idx}. {record_type} | {record['category']} | "
                f"¥{record['amount']:.2f} | {record['time']}\n"
            )

        yield event.plain_result(details)

    @filter.command("按类统计")
    async def query_by_category(self, event: AstrMessageEvent):
        """按类别统计支出/收入"""
        user_name = event.get_sender_name()
        records = self._load_records(user_name)

        if not records:
            yield event.plain_result("📊 您还没有记账数据")
            return

        expense_by_cat = {}
        income_by_cat = {}

        for record in records:
            cat = record["category"]
            amount = record["amount"]
            if record["type"] == "expense":
                expense_by_cat[cat] = expense_by_cat.get(cat, 0) + amount
            else:
                income_by_cat[cat] = income_by_cat.get(cat, 0) + amount

        summary = f"📊 {user_name} 的分类统计\n" + "=" * 40 + "\n"

        if expense_by_cat:
            summary += "📉 支出分类：\n"
            for cat, total in sorted(
                expense_by_cat.items(), key=lambda x: x[1], reverse=True
            ):
                summary += f"  {cat}: ¥{total:.2f}\n"

        if income_by_cat:
            summary += "📈 收入分类：\n"
            for cat, total in sorted(
                income_by_cat.items(), key=lambda x: x[1], reverse=True
            ):
                summary += f"  {cat}: ¥{total:.2f}\n"

        # 获取 AI 评价
        analysis_data = (
            summary.replace("=" * 40, "").strip() + f"\n总记录数: {len(records)}"
        )
        ai_eval = await self._get_ai_evaluation(
            user_name, analysis_data, event.unified_msg_origin
        )

        yield event.plain_result(summary + ai_eval)

    @filter.command("删除账单")
    async def delete_record(self, event: AstrMessageEvent):
        """删除指定账单。用法: 删除账单 <序号>

        先使用 查账详情 获取序号，然后删除指定序号的账单
        """
        user_name = event.get_sender_name()
        message = event.message_str.strip()

        match = re.search(r"删除账单[\s\n]+(\d+)", message)

        if not match:
            yield event.plain_result(
                "❌ 格式错误！用法: 删除账单 <序号>\n"
                "先使用 查账详情 获取序号"
            )
            return

        index = int(match.group(1))
        records = self._load_records(user_name)

        if not records:
            yield event.plain_result("📋 您还没有记账数据")
            return

        records = sorted(records, key=lambda x: x["timestamp"], reverse=True)

        if index < 1 or index > len(records[-20:]):
            yield event.plain_result(
                f"❌ 序号无效！请输入 1-{len(records[-20:])} 之间的序号"
            )
            return

        record_to_delete = records[-20:][index - 1]

        records.remove(record_to_delete)
        self._save_records(user_name, records)

        record_type = "收入" if record_to_delete["type"] == "income" else "支出"
        yield event.plain_result(
            f"✅ 已删除该账单\n"
            f"类型: {record_type}\n"
            f"类别: {record_to_delete['category']}\n"
            f"金额: ¥{record_to_delete['amount']:.2f}\n"
            f"时间: {record_to_delete['time']}"
        )

    async def _save_record(
        self, user_name: str, record_type: str, category: str, amount: float
    ):
        """将记录保存到用户的JSON文件"""
        records = self._load_records(user_name)

        now = datetime.now()
        record = {
            "type": record_type,
            "category": category,
            "amount": amount,
            "timestamp": now.isoformat(),
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        records.append(record)
        self._save_records(user_name, records)

    def _load_records(self, user_name: str) -> list:
        """从用户的JSON文件加载记录"""
        user_file = self._get_user_file(user_name)
        try:
            if user_file.exists():
                with open(user_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载 {user_name} 的记账数据失败: {e}")
        return []

    def _save_records(self, user_name: str, records: list):
        """将记录保存到用户的JSON文件"""
        user_file = self._get_user_file(user_name)
        try:
            with open(user_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 {user_name} 的记账数据失败: {e}")

    async def terminate(self):
        """插件销毁方法"""
        logger.info("记账插件已停用")