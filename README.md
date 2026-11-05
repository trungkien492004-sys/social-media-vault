# 🌐 Social Media Media Vault

Ứng dụng web Fullstack cao cấp phục vụ trích xuất, phân loại và lưu trữ media (ảnh gốc độ phân giải cao nhất & video không logo / watermark) từ **TikTok**, **Instagram**, **Threads**, và **Facebook**.

Hệ thống được thiết kế tối ưu để có thể chạy cục bộ trên máy tính (Windows / Mac / Linux) hoặc **Deploy lên Cloud Miễn Phí (Render.com, Railway)** mà không lo bị chặn CORS.

---

## ✨ Tính Năng Nổi Bật

1. **Trích xuất đa nền tảng**:
   - **TikTok**: Tích hợp engine trích xuất video HD siêu tốc **hoàn toàn sạch logo (No Watermark)** và bóc tách trọn bộ album ảnh (Photo Slideshow).
   - **Instagram & Threads**: Tải ảnh gốc độ phân giải cao, Reels, video bài viết, album carousel.
   - **Facebook**: Tải Facebook Reels, video Watch chất lượng cao.
2. **Cá nhân hóa & Tổ chức dữ liệu**:
   - Tự do đặt **Tên tùy chỉnh** (VD: *"Thầy Kiên"*, *"Khách hàng A"*, *"Mẫu ảnh X"*).
   - Thêm **Ghi chú & Tags** (VD: *"Tài liệu Toán HK1"*, *"Video dạy học"*).
   - Tùy chọn lọc định dạng khi tải: `Tất cả ảnh & video`, `Chỉ ảnh`, hoặc `Chỉ video`.
   - Cấu trúc thư mục logic tự động: `/vault/{Tên_Tùy_Chỉnh}_{Platform}_{Vault_ID}/`.
3. **Tiến trình thời gian thực (Real-time SSE)**:
   - Thanh tiến trình trực quan hiển thị trạng thái từng bước: *Đang phân tích link -> Đã tìm thấy X ảnh, Y video -> Đã tải 45/120 file*.
   - Thanh cuộn ảnh nhỏ (live feed) hiển thị ngay lập tức các tệp vừa được lưu vào máy chủ.
4. **Kho Thư Viện Media (Media Vault Gallery)**:
   - Giao diện Dark Mode sang trọng, hỗ trợ xem dạng lưới (Grid), responsive mượt mà trên điện thoại di động và máy tính.
   - Bộ lọc theo Nền tảng (*Tất cả, TikTok, Instagram, Threads, Facebook*).
   - Tìm kiếm nhanh theo Tên định danh hoặc Ghi chú.
   - Trình xem trước (Lightbox) ảnh phóng to và Video Player tích hợp sẵn.
5. **Nén & Tải về trọn gói 1-Click (.ZIP)**:
   - Nút "Tải file .ZIP" tự động đóng gói toàn bộ media của người đó thành một file .ZIP duy nhất để lưu về máy tính hoặc điện thoại.
6. **Xử lý đăng nhập bằng cookies.txt**:
   - Giao diện trực quan cho phép tải lên file `cookies.txt` (từ tiện ích *Get cookies.txt LOCALLY*) để vượt qua các rào cản đăng nhập của Meta (Facebook / Instagram).

---

## 🏗️ Cấu Trúc Thư Mục Dự Án

```
social-media-vault/
├── app/
│   ├── config.py           # Quản lý cấu hình, biến môi trường & đường dẫn
│   ├── database.py         # Kết nối SQLAlchemy SQLite & khởi tạo bảng
│   ├── models.py           # Database Schema (Vault & MediaItem)
│   ├── schemas.py          # Pydantic v2 request & response schemas
│   ├── extractor.py        # Engine trích xuất (TikWM API, yt-dlp & safe downloader)
│   ├── task_manager.py     # Quản lý tác vụ ngầm & Server-Sent Events (SSE)
│   └── routers/
│       ├── tasks.py        # API kích hoạt tác vụ & stream tiến độ
│       ├── vaults.py       # API quản lý kho, xem chi tiết & nén file ZIP
│       └── settings.py     # API quản lý file cookies.txt
├── static/
│   ├── index.html          # Giao diện người dùng responsive Dark Mode
│   └── js/
│       └── app.js          # Logic tương tác UI, gọi API, SSE & Lightbox
├── data/                   # Thư mục lưu database SQLite (vault.db)
├── vault/                  # Thư mục lưu trữ media thực tế
├── cookies/                # Thư mục lưu file cookies.txt
├── Dockerfile              # Dockerfile chuẩn hóa (có sẵn ffmpeg)
├── docker-compose.yml      # Chạy 1 lệnh với Docker Compose
├── render.yaml             # Cấu hình Blueprint Deploy 1-Click Render.com
├── Procfile                # Chạy trên Heroku / Railway
├── requirements.txt        # Danh sách thư viện Python
├── main.py                 # File khởi động FastAPI
└── README.md
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Cục Bộ (Local)

### Yêu cầu tiên quyết:
- Máy tính đã cài **Python 3.10+**
- (Khuyến nghị) Đã cài **FFmpeg** để hỗ trợ ghép định dạng video âm thanh cao nhất.

### Bước 1: Mở Terminal và di chuyển vào thư mục dự án
```bash
cd social-media-vault
```

### Bước 2: Tạo môi trường ảo và cài đặt thư viện
```bash
# Tạo môi trường ảo
python -m venv venv

# Kích hoạt môi trường:
# Trên Windows:
.\venv\Scripts\activate
# Trên macOS / Linux:
source venv/bin/activate

# Cài đặt toàn bộ thư viện cần thiết
pip install -r requirements.txt
```

### Bước 3: Khởi động máy chủ
```bash
python main.py
# Hoặc: uvicorn main:app --reload --port 8000
```

### Bước 4: Truy cập ứng dụng
Mở trình duyệt web và truy cập địa chỉ:
👉 **`http://localhost:8000`**

---

## 🐳 Chạy Bằng Docker / Docker Compose

Nếu bạn đã cài Docker Desktop, bạn có thể chạy ứng dụng chỉ với 1 lệnh mà không cần cài Python hoặc FFmpeg:

```bash
docker-compose up --build -d
```
Truy cập: **`http://localhost:8000`**

---

## ☁️ Hướng Dẫn Deploy Lên Cloud Miễn Phí (Render.com)

Render.com cung cấp gói Free Web Service hỗ trợ Docker container hoàn toàn miễn phí.

### Bước 1: Đưa code lên GitHub
1. Mở trang [github.com](https://github.com) và tạo một Repository mới (ví dụ: `social-media-vault`).
2. Mở terminal tại thư mục dự án và đẩy code lên GitHub:
```bash
git init
git add .
git commit -m "Initial commit of Social Media Vault"
git branch -M main
git remote add origin https://github.com/TÊN_GITHUB_CỦA_BẠN/social-media-vault.git
git push -u origin main
```

### Bước 2: Deploy trên Render.com
1. Đăng ký/Đăng nhập tại [https://render.com](https://render.com).
2. Nhấn nút **New +** ở góc phải -> chọn **Web Service**.
3. Chọn **Build and deploy from a Git repository** -> Kết nối tài khoản GitHub của bạn và chọn repository `social-media-vault`.
4. Điền các thông tin:
   - **Name**: `social-media-vault` (hoặc tên tùy thích)
   - **Region**: Chọn *Singapore* (gần Việt Nam nhất, tốc độ cao)
   - **Language / Runtime**: Chọn **Docker** (Render sẽ tự động dùng `Dockerfile` đã chuẩn bị sẵn có FFmpeg)
   - **Instance Type**: Chọn **Free** ($0/month)
5. Nhấn **Create Web Service**.
6. Render sẽ tự động build image Docker và khởi động server. Sau 2-3 phút, bạn sẽ nhận được đường link truy cập công khai dạng:
   👉 **`https://social-media-vault-xxxx.onrender.com`**

Bạn có thể mở đường link này trên điện thoại hoặc máy tính bất kỳ lúc nào!

---

## 🍪 Hướng Dẫn Sử Dụng `cookies.txt` (Dành cho Facebook & Instagram)

Các bài viết công khai trên TikTok có thể tải ngay mà không cần tài khoản. Tuy nhiên, với Facebook và Instagram, Meta thường yêu cầu phiên đăng nhập:

1. Trên trình duyệt máy tính (Chrome/Brave/Edge), cài tiện ích miễn phí:
   👉 **Get cookies.txt LOCALLY** (trên Chrome Web Store).
2. Đăng nhập vào Facebook (`facebook.com`) và Instagram (`instagram.com`).
3. Nhấp vào biểu tượng tiện ích ở thanh công cụ trình duyệt -> chọn **Export cookies.txt** để tải file về máy.
4. Trên giao diện web Social Media Vault:
   - Nhấp vào nút **Cài đặt Cookie** (góc trên bên phải).
   - Kéo thả file `cookies.txt` vừa tải lên và nhấn **Tải lên và Áp dụng**.
5. Hệ thống sẽ lập tức nhận diện phiên đăng nhập và cho phép bạn tải album, video riêng tư hoặc bài viết bị hạn chế.

---

## 🛡️ Giấy Phép & Lưu Ý
- Ứng dụng phục vụ mục đích sao lưu cá nhân, lưu trữ tài liệu học tập, nghiên cứu và quản lý dữ liệu chính chủ.
- Vui lòng tuân thủ bản quyền nội dung và điều khoản dịch vụ của các nền tảng mạng xã hội.

## Lưu trữ vĩnh viễn với Supabase (khuyên dùng khi deploy Render Free)

Render Free xóa ổ đĩa khi ngủ/redeploy. Để không mất dữ liệu, dùng Supabase miễn phí:

1. Tạo project tại https://supabase.com (đặt mật khẩu database, nhớ mật khẩu này).
2. **Database:** Project Settings → Database → *Connection string* → chọn **Session pooler** (URI), thay `[YOUR-PASSWORD]` bằng mật khẩu.
3. **Storage key:** Project Settings → API → copy **Project URL** và khóa **service_role** (giữ bí mật, không đưa lên GitHub).
4. Trong Render Dashboard → service → **Environment**, thêm:
   | Biến | Giá trị |
   |------|---------|
   | `DATABASE_URL` | chuỗi kết nối Session pooler ở bước 2 |
   | `SUPABASE_URL` | Project URL, ví dụ `https://abcd.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | khóa `service_role` |
   | `SUPABASE_BUCKET` | `vault` (ứng dụng tự tạo bucket công khai này) |
5. Lưu để Render deploy lại.

Cách hoạt động: ảnh/video được tải lên Supabase Storage ngay sau khi tải, link lưu trong database, bản trên đĩa bị xóa. `cookies.txt` được lưu trong database và tự khôi phục khi khởi động. Nếu không đặt các biến này, ứng dụng vẫn chạy như cũ (lưu trên đĩa, SQLite).

Giới hạn: gói Free của Supabase cho mỗi file tối đa 50 MB và tổng 1 GB lưu trữ. File lớn hơn 50 MB chỉ nằm tạm trên đĩa Render.

## Nhi?u ngu?i d�ng v� b?ng qu?n tr?

- Ngu?i dang k� **d?u ti�n** l� qu?n tr? vi�n (admin). M?i ngu?i d�ng ch? th?y kho v� cookie c?a m�nh.
- Admin c� n�t **Qu?n tr?**: xem danh s�ch ngu?i d�ng, xem/t?i/x�a kho c?a t?ng ngu?i, kh�a ho?c x�a t�i kho?n.
- Bi?n m�i tru?ng t�y ch?n tr�n Render: `INVITE_CODE` (ch? ai c� m� m?i m?i dang k� du?c), `REGISTRATION_OPEN=false` (d�ng dang k�), `USER_QUOTA_MB` (gi?i h?n dung lu?ng m?i ngu?i, m?c d?nh 300, admin kh�ng b? gi?i h?n), `SECRET_KEY` (kh�a k� phi�n dang nh?p; kh�ng d?t th� t? sinh v� luu trong database).
- Web ch?n Google l?p ch? m?c (robots.txt + noindex).

