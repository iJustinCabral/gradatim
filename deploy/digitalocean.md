# Deploy Gradatim on DigitalOcean

## Option 1: Docker (Recommended)

### 1. Create a Droplet

- Image: **Docker on Ubuntu 22.04** (from Marketplace)
- Plan: **Basic $6/mo** (1 vCPU, 1 GB RAM) is enough for MVP
- Region: Choose closest to your users

### 2. SSH in and deploy

```bash
ssh root@YOUR_DROPLET_IP

git clone https://github.com/YOUR_USER/gradatim.git
cd gradatim

# Build and run
docker compose up -d

# Check it's running
docker compose logs -f
```

### 3. Open the firewall

```bash
ufw allow 8080/tcp
```

Visit `http://YOUR_DROPLET_IP:8080`

---

## Option 2: Bare metal

```bash
ssh root@YOUR_DROPLET_IP

git clone https://github.com/YOUR_USER/gradatim.git
cd gradatim

./deploy/setup.sh
```

This installs a systemd service. Check status:

```bash
systemctl status gradatim
journalctl -u gradatim -f
```

---

## Add a domain + HTTPS (optional)

```bash
apt install -y nginx certbot python3-certbot-nginx

# Create Nginx config
cat > /etc/nginx/sites-available/gradatim <<'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -s /etc/nginx/sites-available/gradatim /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Get HTTPS certificate
certbot --nginx -d your-domain.com
```
