from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_token
from app.models.database import get_db
from app.models.schemas import User


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else None
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    user = db.query(User).filter(User.username == username).first()
    if not user or user.is_active != 1:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.is_admin != 1:
        raise HTTPException(status_code=403, detail="无权限访问该功能")
    return current_user
