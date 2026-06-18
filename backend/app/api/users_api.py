from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth_deps import require_admin
from app.core.permissions import validate_permissions
from app.core.security import hash_password
from app.models.database import get_db
from app.models.schemas import User, UserOut


router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreateIn(BaseModel):
    username: str
    password: str
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: int = 1
    is_admin: int = 0
    permissions: list[str] = []

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("用户名不能为空")
        return stripped

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.strip()) < 6:
            raise ValueError("密码至少 6 位")
        return value

    @field_validator("is_active", "is_admin")
    @classmethod
    def validate_flag(cls, value: int) -> int:
        return 1 if value else 0

    @field_validator("permissions")
    @classmethod
    def validate_permission_keys(cls, value: list[str]) -> list[str]:
        return validate_permissions(value)


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[int] = None
    is_admin: Optional[int] = None
    permissions: Optional[list[str]] = None

    @field_validator("is_active", "is_admin")
    @classmethod
    def validate_optional_flag(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return 1 if value else 0

    @field_validator("permissions")
    @classmethod
    def validate_optional_permission_keys(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return validate_permissions(value)


class ResetPasswordIn(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.strip()) < 6:
            raise ValueError("密码至少 6 位")
        return value


def _admin_count(db: Session) -> int:
    return db.query(User).filter(User.is_admin == 1, User.is_active == 1).count()


def _ensure_not_last_admin(db: Session, user: User, *, next_is_admin: int | None = None, next_is_active: int | None = None) -> None:
    current_admin = user.is_admin == 1 and user.is_active == 1
    future_admin = (user.is_admin if next_is_admin is None else next_is_admin) == 1
    future_active = (user.is_active if next_is_active is None else next_is_active) == 1
    if current_admin and not (future_admin and future_active) and _admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="不能禁用或降级最后一个管理员")


@router.get("", response_model=dict)
def list_users(
    keyword: Optional[str] = Query(None),
    is_active: Optional[int] = Query(None),
    permission: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(User)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(User.username.ilike(like), User.name.ilike(like), User.phone.ilike(like), User.email.ilike(like)))
    if is_active is not None:
        q = q.filter(User.is_active == (1 if is_active else 0))
    users = q.order_by(User.id).all()
    if permission:
        users = [user for user in users if permission in (user.permissions or [])]
    return {"code": 0, "data": [UserOut.model_validate(user) for user in users]}


@router.post("", response_model=dict)
def create_user(
    payload: UserCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        name=payload.name.strip() if payload.name else None,
        phone=payload.phone.strip() if payload.phone else None,
        email=payload.email.strip() if payload.email else None,
        is_active=payload.is_active,
        is_admin=payload.is_admin,
        permissions=[] if payload.is_admin else payload.permissions,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"code": 0, "data": UserOut.model_validate(user)}


@router.patch("/{user_id}", response_model=dict)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if current_user.id == user.id and payload.is_active == 0:
        raise HTTPException(status_code=400, detail="不能停用当前登录管理员")
    _ensure_not_last_admin(db, user, next_is_admin=payload.is_admin, next_is_active=payload.is_active)

    if payload.name is not None:
        user.name = payload.name.strip() or None
    if payload.phone is not None:
        user.phone = payload.phone.strip() or None
    if payload.email is not None:
        user.email = payload.email.strip() or None
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.permissions is not None:
        user.permissions = [] if user.is_admin else payload.permissions
    if user.is_admin:
        user.permissions = []

    db.commit()
    db.refresh(user)
    return {"code": 0, "data": UserOut.model_validate(user)}


@router.post("/{user_id}/reset-password", response_model=dict)
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.hashed_password = hash_password(payload.password)
    db.commit()
    return {"code": 0, "data": {"id": user.id}}
