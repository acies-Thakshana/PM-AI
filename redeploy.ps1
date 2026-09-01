# PM-AI Redeploy Script
# Run this after starting the EC2 instance: .\redeploy.ps1

$KEY = "C:\Users\Thakshana\.ssh\pm-ai-key.pem"
$BUCKET = "pm-ai-frontend-thakshana"
$FRONTEND = "C:\Users\Thakshana\Desktop\PM AI\PM-AI\frontend"
$BACKEND_APP = "C:\Users\Thakshana\Desktop\PM AI\PM-AI\backend\app"

# Step 1: Get EC2 IP from user
$EC2_IP = Read-Host "Enter your EC2 Public IPv4 address"

Write-Host "`n[1/4] Updating frontend API URL..." -ForegroundColor Cyan
[System.IO.File]::WriteAllText(
    "$FRONTEND\.env.production",
    "VITE_API_BASE_URL=http://$EC2_IP`:8000`n",
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "[2/4] Building frontend..." -ForegroundColor Cyan
Set-Location $FRONTEND
npm run build

Write-Host "[3/4] Uploading frontend to S3..." -ForegroundColor Cyan
aws s3 sync "$FRONTEND\dist" "s3://$BUCKET" --delete

Write-Host "[4/4] Uploading backend and restarting service..." -ForegroundColor Cyan
scp -i $KEY -r "$BACKEND_APP" "ec2-user@$EC2_IP`:/home/ec2-user/pm-ai-backend/"
ssh -i $KEY "ec2-user@$EC2_IP" "sudo systemctl restart pm-ai"

Write-Host "`nDone! App is live at:" -ForegroundColor Green
Write-Host "http://$BUCKET.s3-website.eu-north-1.amazonaws.com" -ForegroundColor Green
