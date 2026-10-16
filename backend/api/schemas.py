"""请求体模型：集中定义，便于交叉比对前后端字段。

放在一个文件里的理由：这些模型是「接口契约」本身，
散落到各 router 后，改一个字段要翻十个文件才能确认没有遗漏。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    username: str
    password: str


class ProcessBody(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_name: Optional[str] = None
    country: Optional[str] = None
    user_goal: Optional[str] = None
    tools: Optional[list[str]] = None


class RecommendReplyBody(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_name: Optional[str] = None
    country: Optional[str] = None
    note: Optional[str] = None
    save: bool = True


class AgentRunBody(BaseModel):
    inquiry_id: Optional[str] = None
    user_goal: str = ""
    tools: Optional[list[str]] = None
    query: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""
    # 透传已有中间结果，便于单独跑下游 Agent
    requirement: Optional[dict] = None
    vendor_match: Optional[dict] = None
    compare: Optional[dict] = None
    pipeline: Optional[dict] = None


class SampleBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    product: str = ""
    # 规格明细（礼品打样常踩坑的字段）
    color: str = ""
    color_code: str = ""
    material: str = ""
    size_spec: str = ""
    finish: str = ""
    logo_process: str = ""
    logo_position: str = ""
    sample_qty: str = ""
    sample_fee: str = ""
    tracking_no: str = ""
    status: str = "待打样"
    eta: str = ""
    notes: str = ""


class ApprovalDecideBody(BaseModel):
    approve: bool
    final_text: str = ""


class SearchBody(BaseModel):
    query: str
    top_k: int = Field(default=4, ge=1, le=12)


class ChatAskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    inquiry_id: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""


class AssistantChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    inquiry_id: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""
    file_path: str = ""
    force_vision: bool = False


class CustomerBody(BaseModel):
    id: Optional[str] = None
    name: str
    country: str = ""
    contact: str = ""
    email: str = ""
    phone: str = ""
    channel: str = "email"
    tags: Any = ""
    priority: str = "medium"
    last_contact: str = ""
    preferences: str = ""
    memo: str = ""
    notes: str = ""
    company_address: str = ""
    website: str = ""
    timezone: str = ""
    payment_terms: str = ""
    preferred_incoterms: str = ""
    preferred_colors: str = ""
    preferred_materials: str = ""
    owner: Optional[str] = None
    stage: str = ""
    source: str = ""
    blacklist: bool = False


class VendorBody(BaseModel):
    id: Optional[str] = None
    name: str
    region: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""
    categories: Any = ""
    colors: str = ""
    materials: str = ""
    finishes: str = ""
    logo_processes: str = ""
    custom_color: str = ""
    sample_lead_days: str = ""
    payment_terms: str = ""
    certifications: str = ""
    quality_score: int = 3
    bulk_lead_days: str = ""
    capacity_note: str = ""
    strengths: str = ""
    moq_note: str = ""
    price_note: str = ""
    preferences: str = ""
    memo: str = ""
    notes: str = ""
    active: bool = True


class InquiryBody(BaseModel):
    id: Optional[str] = None
    customer_id: str = ""
    customer_name: str = ""
    country: str = ""
    from_email: str = ""
    subject: str = ""
    body: str = ""
    status: str = "pending"
    qty: str = ""
    target_price: str = ""
    currency: str = "USD"
    incoterms: str = "FOB"
    destination: str = ""
    deadline: str = ""
    product_name: str = ""
    color: str = ""
    material: str = ""
    size_spec: str = ""
    priority: str = "medium"
    source_channel: str = "email"


class QuoteLine(BaseModel):
    product: str = ""
    color: str = ""
    material: str = ""
    qty: str = ""
    unit_price: str = ""
    moq: str = ""
    lead_days: str = ""
    notes: str = ""
    cost_price: str = ""
    floor_price: str = ""


class QuotationBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    customer_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    currency: str = "USD"
    incoterms: str = "FOB"
    valid_until: str = ""
    status: str = "draft"
    total: str = ""
    notes: str = ""
    lines: list[QuoteLine] = Field(default_factory=list)
    floor_price: str = ""
    cost_price: str = ""
    target_price: str = ""
    lost_reason: str = ""
    approve_below_floor: bool = False
    updated_by: str = ""


class QuotationVersionBody(BaseModel):
    lines: list[QuoteLine] = Field(default_factory=list)
    note: str = ""


class QuotationLostBody(BaseModel):
    reason: str = ""


class QuotationStatusBody(BaseModel):
    status: str


class OrderBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    quotation_id: str = ""
    customer_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    product: str = ""
    color: str = ""
    material: str = ""
    qty: str = ""
    unit_price: str = ""
    currency: str = "USD"
    deposit: str = ""
    status: str = "待定金"
    etd: str = ""
    tracking_no: str = ""
    notes: str = ""
    delivery_date: str = ""
    deposit_due: str = ""
    owner: str = ""


class PaymentBody(BaseModel):
    payment_id: str = ""
    amount: str = ""
    method: str = ""
    note: str = ""


class MilestoneBody(BaseModel):
    key: str
    status: str = "done"
    actual_date: str = ""
    note: str = ""


class OrderMetaBody(BaseModel):
    delivery_date: Optional[str] = None
    deposit_due: Optional[str] = None
    etd: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    owner: Optional[str] = None
    tracking_no: Optional[str] = None


class TransferBody(BaseModel):
    to_employee: str = ""


class RecycleBody(BaseModel):
    days: Optional[int] = None


class FollowupBody(BaseModel):
    id: Optional[str] = None
    customer_id: str = ""
    customer_name: str = ""
    inquiry_id: str = ""
    due_date: str = ""
    reason: str = ""
    suggested_action: str = ""
    priority: str = "medium"
    status: str = "open"


class ActiveBody(BaseModel):
    active: bool


class PasswordBody(BaseModel):
    new_password: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    name: str
    role: str = "外贸业务员"
    email: str = ""
    is_admin: bool = False
    can_approve: bool = False
