# Apple Silicon (M1/M2/M3) Fix

## Problem

If you're using an Apple Silicon Mac (M1, M2, or M3), Docker builds ARM64 images by default. However, Azure Container Apps requires **AMD64 (x86_64)** images.

## Error Message

```
image OS/Arc must be linux/amd64 but found linux/arm64
```

## ✅ Solution

The deployment scripts have been updated to automatically build for the correct architecture. Just run:

```bash
./deploy-azure-local-build.sh
```

The script now uses `--platform linux/amd64` flag automatically.

## Manual Build (If Needed)

If you're building manually, always specify the platform:

```bash
# ✅ Correct - builds for Azure (AMD64)
docker build --platform linux/amd64 -t nebulous-bot .

# ❌ Wrong - builds for your Mac (ARM64)
docker build -t nebulous-bot .
```

## Why This Happens

- **Apple Silicon Macs** use ARM64 architecture
- **Azure Container Apps** run on AMD64 (Intel/x86_64) architecture
- Docker builds for your local architecture by default
- The `--platform` flag forces Docker to build for a different architecture

## Performance Note

Building for AMD64 on Apple Silicon uses emulation, so:
- ✅ It works perfectly
- ⚠️ It's slightly slower than native ARM64 builds (but still fine)
- ✅ The final image runs normally on Azure

## Testing Locally

You can test the AMD64 image on your Mac:

```bash
# Build for AMD64
docker build --platform linux/amd64 -t nebulous-bot .

# Run with platform specified
docker run --platform linux/amd64 -p 8000:8000 nebulous-bot
```

Docker Desktop will emulate AMD64 on your ARM64 Mac.

## Buildx (Alternative Method)

If you want more control, you can use Docker Buildx:

```bash
# Create a builder
docker buildx create --name multiplatform --use

# Build for AMD64
docker buildx build \
  --platform linux/amd64 \
  -t nebulous-bot \
  --load \
  .
```

## Verification

Check what platform your image is built for:

```bash
# Inspect the image
docker inspect nebulous-bot | grep Architecture

# Should show: "Architecture": "amd64"
```

## Summary

**For Azure deployment on Apple Silicon:**
- ✅ Always use `--platform linux/amd64`
- ✅ Use the provided deployment scripts (they handle this automatically)
- ✅ Docker will emulate AMD64 (works perfectly, slightly slower build)
- ✅ The image will run normally on Azure

---

**Quick Fix:** Just run `./deploy-azure-local-build.sh` - it's already fixed! 🚀

