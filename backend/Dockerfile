FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.30.0" \
    "sqlalchemy>=2.0.0" \
    "pymysql>=1.1.0" \
    "alembic>=1.13.0" \
    "pandas>=2.2.0" \
    "openpyxl>=3.1.0" \
    "python-multipart>=0.0.9" \
    "python-dotenv>=1.0.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "python-jose[cryptography]>=3.3.0" \
    "passlib[bcrypt]>=1.7.4" \
    "bcrypt==4.0.1"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
