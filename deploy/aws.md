# Deploy Gradatim on AWS

## Option 1: EC2 + Docker

### 1. Launch an instance

- AMI: **Amazon Linux 2023** or **Ubuntu 22.04**
- Instance type: **t3.micro** (free tier) or **t3.small**
- Security group: Allow inbound TCP **8080** (or 80/443 with Nginx)

### 2. SSH in and install Docker

```bash
ssh -i your-key.pem ec2-user@YOUR_INSTANCE_IP

# Amazon Linux 2023
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# Install docker compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Log out and back in for group change
exit
ssh -i your-key.pem ec2-user@YOUR_INSTANCE_IP
```

### 3. Deploy

```bash
git clone https://github.com/YOUR_USER/gradatim.git
cd gradatim

docker compose up -d
docker compose logs -f
```

---

## Option 2: EC2 bare metal

```bash
ssh -i your-key.pem ec2-user@YOUR_INSTANCE_IP

git clone https://github.com/YOUR_USER/gradatim.git
cd gradatim

sudo ./deploy/setup.sh
```

---

## Option 3: AWS App Runner (container)

1. Push the Docker image to ECR:
```bash
aws ecr create-repository --repository-name gradatim
aws ecr get-login-password | docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.REGION.amazonaws.com
docker build -t gradatim .
docker tag gradatim:latest YOUR_ACCOUNT.dkr.ecr.REGION.amazonaws.com/gradatim:latest
docker push YOUR_ACCOUNT.dkr.ecr.REGION.amazonaws.com/gradatim:latest
```

2. Create an App Runner service in the AWS console:
   - Source: ECR image
   - Port: 8080
   - Health check: `/healthz`
   - CPU: 1 vCPU, Memory: 2 GB

---

## HTTPS with ALB

1. Request a certificate in **ACM** for your domain
2. Create an **Application Load Balancer**:
   - Listener: HTTPS 443 → Target group on port 8080
   - Health check path: `/healthz`
3. Point your domain's DNS to the ALB
