"""
请求体模型（Pydantic v2）：进门先校验，非法参数在进业务前就被挡掉。

约定：所有模型字段命名与前端提交字段一致，多余字段忽略（extra="ignore"），
缺省值与原逻辑保持一致，避免破坏已有前端调用。
"""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

PHONE_RE = r"^1\d{10}$"

# 字段中文名，用于把 Pydantic 的英文报错转成给用户看的话
FIELD_CN = {
    "phone": "手机号", "pwd": "密码", "code": "验证码", "name": "姓名", "avatar": "头像",
    "region": "所在地区", "detail": "详细地址", "is_default": "默认地址", "tpl_id": "优惠券",
    "slot_id": "号源", "doctor_id": "医生", "dept": "科室", "mode": "问诊方式",
    "symptom": "病情描述", "chat_id": "问诊单", "text": "消息内容", "duration": "通话时长",
    "med_id": "药品", "qty": "数量", "pkg_id": "套餐", "rx_id": "处方", "addr_id": "收货地址",
    "coupon_id": "优惠券", "note": "备注", "pay": "支付方式", "cat": "分类", "months": "月数",
    "id": "编号",
}
TYPE_CN = {
    "missing": "缺少参数：{f}",
    "string_pattern_mismatch": "{f}格式不正确",
    "string_type": "{f}必须是文本",
    "string_too_short": "{f}至少 {n} 位",
    "string_too_long": "{f}最多 {n} 位",
    "int_parsing": "{f}必须是数字",
    "int_type": "{f}必须是数字",
    "greater_than_equal": "{f}不能小于 {n}",
    "less_than_equal": "{f}不能大于 {n}",
    "literal_error": "{f}取值不合法",
}


def human_error(errors):
    """取第一条校验错误，转成一句中文提示"""
    e = errors[0]
    loc = [x for x in e["loc"] if x != "body"]
    f = FIELD_CN.get(loc[-1] if loc else "", loc[-1] if loc else "参数")
    tpl = TYPE_CN.get(e["type"], "{f}不合法")
    ctx = e.get("ctx") or {}
    n = ctx.get("min_length") or ctx.get("max_length") or ctx.get("ge") or ctx.get("le") or ""
    return tpl.format(f=f, n=n)


class Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------- 账号 ----------
class SmsIn(Base):
    phone: str = Field(pattern=PHONE_RE)


class RegisterIn(Base):
    phone: str = Field(pattern=PHONE_RE)
    pwd: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=6)
    name: str = Field(default="", max_length=12)


class LoginIn(Base):
    phone: str = Field(pattern=PHONE_RE)
    pwd: str = Field(min_length=1, max_length=32)


class ProfileIn(Base):
    name: str = Field(default="", max_length=12)
    avatar: str = Field(default="", max_length=16)


# ---------- 地址 ----------
class AddressIn(Base):
    name: str = Field(min_length=1, max_length=20)
    phone: str = Field(pattern=PHONE_RE)
    region: str = Field(min_length=1, max_length=60)
    detail: str = Field(min_length=1, max_length=120)
    is_default: int = Field(default=0, ge=0, le=1)


class AddressPatchIn(Base):
    """编辑地址：字段都可选，不传即保持原值"""
    name: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, pattern=PHONE_RE)
    region: str | None = Field(default=None, max_length=60)
    detail: str | None = Field(default=None, max_length=120)
    is_default: int = Field(default=0, ge=0, le=1)


# ---------- 优惠券 / 挂号 ----------
class ClaimIn(Base):
    tpl_id: int = Field(ge=1)


class ApptIn(Base):
    slot_id: int = Field(ge=1)


# ---------- 问诊 ----------
class ChatStartIn(Base):
    doctor_id: int = Field(default=0, ge=0)  # 0 = 不指定医生，由系统按科室派单
    dept: str = Field(default="", max_length=20)
    mode: str = Field(default="text", max_length=16)  # text / voice / video，非法值由业务侧回退 text
    symptom: str = Field(min_length=1, max_length=500)


class ChatPayIn(Base):
    pay: str = Field(default="微信")
    coupon_id: int = Field(default=0, ge=0)


class ChatSendIn(Base):
    chat_id: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=1000)


class ChatEndIn(Base):
    chat_id: int = Field(ge=1)
    duration: int = Field(default=0, ge=0, le=7200)


class RxIn(Base):
    chat_id: int = Field(ge=1)


# ---------- 商城 ----------
class CartAddIn(Base):
    med_id: int = Field(ge=1)
    qty: int = Field(default=1, ge=1, le=99)


class CartQtyIn(Base):
    qty: int = Field(ge=0, le=99)


class OrderPreviewIn(Base):
    pkg_id: int = Field(default=0, ge=0)
    coupon_id: int = Field(default=0, ge=0)


class OrderCreateIn(Base):
    pkg_id: int = Field(default=0, ge=0)
    rx_id: int = Field(default=0, ge=0)
    addr_id: int = Field(default=0, ge=0)
    coupon_id: int = Field(default=0, ge=0)
    pay: str = Field(default="微信")
    note: str = Field(default="", max_length=200)


class OrderPayIn(Base):
    pay: str = Field(default="微信")


class NewsIn(Base):
    cat: str = Field(default="", max_length=20)


class ReviewIn(Base):
    """订单商品评价：一单一商品限一次，评分 1~5 星，内容选填（超长截断而非报错）"""
    med_id: int = Field(ge=1)
    rating: int = Field(default=5, ge=1, le=5)
    content: str = Field(default="", max_length=200)
    anon: int = Field(default=0, ge=0, le=1)


class VipIn(Base):
    months: int = Field(default=1, ge=1, le=12)


class RxRejectIn(Base):
    """药师驳回处方：理由选填但落库时兜底为默认话术，患者侧可见"""
    reason: str = Field(default="", max_length=120)


class AllergyIn(Base):
    """过敏史：逗号/顿号分隔的过敏原文本，空串表示清除"""
    allergy: str = Field(default="", max_length=120)
