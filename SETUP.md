# Setup sau khi clone

Tài liệu này mô tả những gì cần chuẩn bị để project chạy được trên một máy
mới. Repository chỉ chứa source/config/schema/docs; secret, model weights,
NIM cache, TensorRT engine, upstream checkout và runtime data không được commit.

## 1. Điều kiện máy

Project cần một Linux host x86 có:

- Git, Bash, `curl`, `jq`, `rg`, `sha256sum`, `make`;
- Python 3.12 và `uv`;
- Docker Engine + Docker Compose plugin;
- NVIDIA driver, NVIDIA Container Toolkit/CDI và Docker GPU access;
- GPU NVIDIA đủ VRAM cho các profile serialized; project giữ reserve 5 GiB;
- disk trống lớn cho image, NIM cache, TensorRT engine và runtime data.

NVIDIA VSS baseline được thiết kế cho Ubuntu 22.04/24.04 và prerequisite
version tương ứng. Host hiện tại của PoC là AlmaLinux 8.10 với RTX PRO 5000
Blackwell; topology này là experimental, không phải topology được NVIDIA
validate cho deployment này. Luôn chạy preflight trước khi tải image/model.

## 2. Clone repository

```bash
git clone https://github.com/KhoiMinh47/Custom-VSS-With-NIMS.git
cd Custom-VSS-With-NIMS
```

Kiểm tra không có file local nhạy cảm trước khi tiếp tục:

```bash
git status --short
git check-ignore -v .secrets/infra.env runtime artifacts .cache .venv
```

## 3. Lấy upstream NVIDIA VSS

Thư mục `third_party/video-search-and-summarization/` bị loại khỏi Git vì
đây là upstream checkout lớn. Cần lấy đúng release trước khi chạy các script
resolve/test của VSS:

```bash
git clone --branch v3.2.1 \
  https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git \
  third_party/video-search-and-summarization
cd third_party/video-search-and-summarization
git checkout 7640d917047cf7b0fd3085eefb8282754b56bc94
cd ../..
```

Xác minh:

```bash
git -C third_party/video-search-and-summarization describe --tags --exact-match
git -C third_party/video-search-and-summarization rev-parse HEAD
```

Kết quả phải là tag `v3.2.1` và commit được ghi trong
`config/models/model-manifest.yaml`. Không patch trực tiếp upstream; project
overlay nằm trong `services/`, `config/` và `deploy/`.

## 4. Tạo thư mục project-local

```bash
make bootstrap
source scripts/env.sh
make verify-paths
```

`make bootstrap` tạo `.venv`, `.cache`, `models`, `runtime`, `artifacts` và
`.secrets` dưới project root. Không chuyển các thư mục này ra `$HOME` hoặc
system path.

## 5. Tạo secret local

### Infrastructure

```bash
cp .env.example .secrets/infra.env
chmod 600 .secrets/infra.env
```

Mở `.secrets/infra.env` và thay các giá trị `REPLACE_WITH_SECRET` bằng password
local cho PostgreSQL, Redis, MinIO và Grafana. File này phải ở mode `600` và
không được commit.

### NVIDIA VSS UI

```bash
cp config/ui/vss-ui.env.example config/ui/vss-ui.env
```

File `config/ui/vss-ui.env` chỉ là local runtime config. File thật bị
`.gitignore` loại khỏi Git; bản public an toàn là
`config/ui/vss-ui.env.example`.

### Phase 15 operator token

Sau khi bootstrap, tạo digest token bằng prompt ẩn:

```bash
bash scripts/configure-phase15-operator.sh <operator-id> admin
```

Plaintext token không được ghi vào file, log, GitHub hoặc chat. API Phase 15
chỉ nên expose trên loopback trong PoC.

### Camera credential

Không sửa `config/cameras/cameras.hybrid.json` để chèn RTSP password. Khi có
camera vật lý, lưu URI bằng workflow secret-safe:

```bash
make camera-save
make camera-probe
make camera-probe-ai
make camera-activate
```

URI chỉ được giữ trong keyring/secret store local. Nếu chưa có camera, dùng
profile replay để kiểm tra video plane; replay không phải bằng chứng scale 10
camera vật lý.

## 6. Preflight host/GPU

```bash
source scripts/env.sh
bash scripts/preflight.sh
make inventory
```

Nếu preflight fail vì host/GPU không nằm trong NVIDIA baseline, không tự bỏ qua
gate. Chỉ dùng override khi operator đã chấp thuận rủi ro và phải giữ evidence
trong `artifacts/preflight/`. Không chạy nhiều GPU-heavy profile đồng thời.

## 7. Chuẩn bị VSS image và NIM cache

NGC key chỉ được load trong shell đã được bảo vệ; không ghi vào `.env`, script,
YAML, log hay README:

```bash
export NGC_API_KEY='<load-from-your-secret-manager-in-this-shell-only>'
```

Resolve đúng release và image manifest:

```bash
bash scripts/resolve-vss-release.sh
bash scripts/pull-vss-core.sh --acknowledge-unsupported-host  # chỉ khi đã được duyệt
```

Profile NIM phải được discover, review compatibility và chọn rõ ràng trước khi
download:

```bash
bash scripts/discover-nim-profiles.sh
export LLM_PROFILE_ID='<reviewed-nemotron-profile-id>'
export VLM_PROFILE_ID='<reviewed-cosmos3-profile-id>'
bash scripts/download-model-cache.sh
```

Cache được lưu dưới `.cache/nim/`, không đưa lên GitHub. Không download toàn
bộ profile và không ép profile dành cho GPU khác. Sau khi tải, chạy smoke test
với image digest/profile đã review; xóa key khỏi shell sau khi hoàn tất.

RT-DETR, Cosmos-Embed1, SigLIP2 và TensorRT engine cũng là external artifacts.
Đặt chúng theo `config/models/model-manifest.yaml`, kiểm tra SHA-256 và giữ
trong `models/` hoặc `.cache/tensorrt/`. Không commit weights/engine.

## 8. Khởi động theo thứ tự

### Infrastructure data plane

```bash
make infra-config
make infra-start
make infra-health
```

Các service gồm Kafka, Elasticsearch, PostgreSQL, Redis, MinIO, Prometheus và
Grafana. Raw video không nằm trong PostgreSQL project; VIOS giữ video plane
riêng.

### Video plane

```bash
make video-config
make video-start
make video-health
```

Để test bằng replay local:

```bash
make video-prepare-simulated
make video-onboard
```

Để dùng camera thật, hoàn tất phần camera credential ở trên rồi kiểm tra
`make camera-status`. Không commit URI/password.

### Phase 15 UI/control plane

```bash
make phase15-config
make phase15-start
make phase15-health
```

Mở `http://127.0.0.1:39510/`. GPU worker, VLM Test, Media Intake, unified BFF
và NVIDIA VSS UI sẽ được start theo compose Phase 15. LLM/VLM vẫn offline hoặc
standby cho tới khi operator bật qua GPU control và admission cho phép.

### Realtime RT-CV (on-demand)

Chỉ chạy khi camera/AI substream, RT-DETR artifact và GPU admission đã sẵn
sàng:

```bash
make rtcv-config
make rtcv-start
make rtcv-health
```

RT-CV realtime tạo metadata/candidate từ camera. Upload VLM Test dùng file-batch
RT-CV riêng, sau đó dừng RT-CV trước khi admit Cosmos3.

## 9. Kiểm tra sau setup

```bash
make phase15-test
.venv/bin/python -m pytest -q
```

Kiểm tra UI/API:

```bash
curl --fail http://127.0.0.1:39510/health/ready
curl --fail 'http://127.0.0.1:39510/api/v1/overview?refresh=true'
```

`standby` của Nemotron/Cosmos3 là trạng thái bình thường khi chưa có lease.
`ready=false` có thể xảy ra nếu RT-CV realtime hoặc camera offline; điều đó
không đồng nghĩa CPU control plane hỏng.

## 10. Dừng và khôi phục an toàn

```bash
make phase15-stop
make camera-live-stop
make video-stop
make infra-stop
```

Các script stop bảo toàn image, volume, model cache, recording, index,
checkpoint và runtime data. Không dùng:

```text
docker compose down -v
docker system prune
docker volume rm
docker rmi
```

Khi provider bị OOM hoặc unavailable, đọc
`docs/runbooks/gpu-oom.md`/`docs/runbooks/nim-down.md`; dừng đúng profile và
revoke lease, không xóa cache để chữa lỗi.

## Những thứ không được đưa lên GitHub

```text
.env và *.env thật
.secrets/
runtime/
artifacts/
.cache/
.venv/
models/ chứa weights
TensorRT engine
video/raw recording/snapshot
RTSP URI thật hoặc password camera
NGC_API_KEY, bearer token, database password
deploy/generated/
third_party/video-search-and-summarization/ checkout local
```

Nếu clone trên máy mới, bắt đầu lại từ bước 3–7; không copy nguyên
`.secrets/`, `runtime/` hoặc `.cache/` từ một máy khác nếu chưa kiểm tra quyền,
owner, model hash và secret policy.
