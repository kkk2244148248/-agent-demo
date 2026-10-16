"""初始化 MySQL FAQ 表并写入种子问答。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config import get_settings
from backend.services.faq_mysql import MysqlFaqStore

SEED = [
    {
        "question": "保温杯厂家是哪家？推荐哪个厂商？",
        "answer": "保温杯优先推荐 V-YH01 义乌星火家居礼品有限公司（浙江义乌）。常规 350/500ml，可丝印/激光刻字，FOB 义乌参考价约 ¥12–22/个（1000+）。联系人：李经理。",
        "tags": "保温杯 V-YH01 厂商",
    },
    {
        "question": "折叠伞可以定制吗？MOQ 多少？",
        "answer": "可以。折叠伞厂商 V-YK05 义乌晴雨伞业支持印花/丝印/直柄自动伞。普通折叠伞 MOQ 约 1000 把，自动伞约 500 把；样品约 5–8 天，大货约 15–22 天。",
        "tags": "雨伞 折叠伞 V-YK05 MOQ",
    },
    {
        "question": "蓝牙音箱和充电宝找哪家？",
        "answer": "数码类找 V-SZ03 深圳创想数码礼品。常见 10000mAh 充电宝、蓝牙音箱、U 盘等，FOB 深圳。注意电池类出口认证与运输限制，下单前核对 CE/FCC/UN38.3。",
        "tags": "数码 音箱 充电宝 V-SZ03",
    },
    {
        "question": "包袋类供应商是谁？",
        "answer": "包袋推荐 V-DG02 东莞织造包袋厂，帆布袋/涤纶袋/电脑包等，可印 Logo。适合展会礼品与商超促销袋。",
        "tags": "包袋 V-DG02",
    },
    {
        "question": "服饰类礼品有哪些厂商？",
        "answer": "服饰礼品走 V-SX04（帽衫/T恤/帽类等）。注意尺码表、成分标与印绣工艺确认，海外订单建议先打样确认色牢度。",
        "tags": "服饰 V-SX04",
    },
    {
        "question": "怎么回复海外客户询价？",
        "answer": "标准流程：1) 确认产品规格/数量/交期/目的港；2) 用知识库匹配 2–3 家厂；3) 报 FOB/可选项；4) 说明样品周期与认证；5) 草稿走「发送审批」后再外发，避免 AI 乱承诺。",
        "tags": "话术 询价 流程",
    },
    {
        "question": "样品进度怎么跟？",
        "answer": "在「样品进度」里登记客户/厂商/状态（打样中、寄出、确认）。也可在 Agent 工具台调用 list_samples / upsert_sample。超期跟进记到「跟进待办」。",
        "tags": "样品 进度",
    },
    {
        "question": "登录账号密码是什么？",
        "answer": "试用账号：liht / chenxw / zhoum，初始密码均为 123456。管理员可在「账号管理」停用离职账号或重置密码。",
        "tags": "登录 账号",
    },
]


def main() -> None:
    s = get_settings()
    print(f"MySQL {s.mysql_host}:{s.mysql_port}/{s.mysql_database} user={s.mysql_user}")
    store = MysqlFaqStore()
    store.ensure_schema()
    n = store.seed_if_empty(SEED)
    store.reload(force=True)
    print(f"seed_inserted={n} total={len(store._rows)} error={store.error!r}")
    for q in ["保温杯厂家", "折叠伞 MOQ", "随便问问没有的"]:
        hits = store.search(q, top_k=1)
        if hits:
            h = hits[0]
            print(f"Q={q} conf={h.confidence:.3f} score={h.score:.3f} -> {h.question[:40]}")
        else:
            print(f"Q={q} no hit")


if __name__ == "__main__":
    main()
