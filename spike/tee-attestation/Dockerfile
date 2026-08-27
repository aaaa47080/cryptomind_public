# TEE 可驗證執行 spike — 部署到 Phala Cloud 的容器。
# 只暴露 /assess（純規則計算），無金流、無私鑰、無外部網路依賴。

FROM python:3.13-slim

WORKDIR /app

# 安裝開源審查核心（版本綁定：report 的 kernel_version 對照公開 repo tag）
COPY pyproject.toml .
COPY safety_kernel/ safety_kernel/
RUN pip install --no-cache-dir .

# spike 程式碼
COPY assess_in_tee.py verify_report.py ./

# /assess 簡易 HTTP 入口（Phala Cloud 需要一個可被呼叫的服務）
RUN pip install --no-cache-dir fastapi uvicorn

COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
