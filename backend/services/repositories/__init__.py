"""仓储层：按业务域切分 `RuntimeStore` 的读写逻辑。

拆分层级说明（从下到上）：

    constants.py   领域常量与规则参数（回收天数、生产节点、收款比例…）
    utils.py       纯函数工具（数字/日期解析、归属与底价的规范化）
    *_repo.py      各业务域仓储：只负责"这个域的数据怎么写才正确"
    mixins.py      把所有域仓储组合成 `StoreMixin`
    ../store.py    `RuntimeStore` —— 加锁、持久化、对外单例

拆分动机：单文件 1700 行时，改一个报价规则要通读全部客户/订单代码。
按业务域切分后，每类规则只落在一个文件里，评审 diff 时范围清晰。
"""
from backend.services.repositories.constants import (
    CUSTOMER_STAGES,
    DEFAULT_PAYMENT_PLAN,
    DEFAULT_RECYCLE_DAYS,
    PRODUCTION_MILESTONES,
)
from backend.services.repositories.mixins import StoreMixin

__all__ = [
    "StoreMixin",
    "CUSTOMER_STAGES",
    "DEFAULT_PAYMENT_PLAN",
    "DEFAULT_RECYCLE_DAYS",
    "PRODUCTION_MILESTONES",
]
