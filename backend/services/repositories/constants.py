"""领域常量：跑单机制里的规则参数集中放这里，避免散落在各仓储文件。"""
from __future__ import annotations

# 私海客户超过该天数无跟进自动回公海
DEFAULT_RECYCLE_DAYS = 30

# 客户生命周期阶段
CUSTOMER_STAGES = ("新询盘", "已报价", "已打样", "已下单", "复购", "沉睡")

# 生产跟单标准节点（按顺序推进，红绿灯据此计算）
PRODUCTION_MILESTONES: tuple[tuple[str, str], ...] = (
    ("deposit", "定金到账"),
    ("po", "排产下单"),
    ("midcheck", "中期进度"),
    ("finalcheck", "尾期验货"),
    ("customs", "报关出货"),
    ("arrived", "到港签收"),
)

# 标准收款比例（定金 + 尾款）
DEFAULT_PAYMENT_PLAN: tuple[tuple[str, float], ...] = (
    ("定金", 0.3),
    ("尾款", 0.7),
)

# 订单处于这些状态时视为「定金已付」
DEPOSIT_PAID_ORDER_STATUS = ("生产中", "已出货", "已签收")

# 不再计入交期风险的终态
ORDER_FINAL_STATUS = ("已签收", "已取消", "已完成")
