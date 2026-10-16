/** 给年纪大的同事看的中文文案 */
export const STATUS_ZH = {
  pending: '待处理',
  processed: '已出草稿',
  awaiting_approval: '等待审批',
  sent: '已发送',
  open: '待跟进',
  done: '已完成',
  approved: '已通过',
  rejected: '已驳回',
  high: '高',
  medium: '中',
  low: '低',
  // 报价 / 订单 / 回款
  draft: '草稿',
  sent_q: '已发出',
  accepted: '客户已接受',
  '待定金': '待定金',
  '生产中': '生产中',
  '已出货': '已出货',
  '已签收': '已签收',
  '已取消': '已取消',
  paid: '已收',
  partial: '部分收款',
  overdue: '逾期',
  pending_pay: '待收',
}

export const INTENT_ZH = {
  inquiry: '一般咨询',
  quote: '询价报价',
  sample: '样品申请',
  complaint: '投诉售后',
  followup: '跟进催促',
  other: '其他',
}

export const ACTION_ZH = {
  process_inquiry: '智能处理询盘',
  submit_approval: '提交发送审批',
  approve: '确认发送',
  reject: '驳回草稿',
  complete_followup: '完成跟进',
  登录系统: '登录系统',
  退出登录: '退出登录',
  添加账号: '添加账号',
  启用账号: '启用账号',
  '停用账号（离职）': '停用账号（离职）',
  重置密码: '重置密码',
  智能处理询盘: '智能处理询盘',
  提交发送审批: '提交发送审批',
  确认发送: '确认发送',
  驳回草稿: '驳回草稿',
  完成跟进: '完成跟进',
  重建知识库: '重建知识库',
}

export function zhStatus(v) {
  return STATUS_ZH[v] || v || '-'
}

export function zhIntent(v) {
  return INTENT_ZH[v] || v || '-'
}

export function zhAction(v) {
  return ACTION_ZH[v] || v || '-'
}
