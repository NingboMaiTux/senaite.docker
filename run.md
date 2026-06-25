# SENAITE Docker Local Run Guide

## 1. Enter the build directory

```powershell
cd d:\AWork\senaite.docker\latest
```

## 2. Build the image

Use the normal build command:

```powershell
docker build -t maitux/senaite:latest .
```

If you want detailed build logs:

```powershell
docker build --progress=plain -t maitux/senaite:latest .
```

If you need to force a full rebuild without cache:

```powershell
docker build --no-cache --progress=plain -t maitux/senaite:latest .
```

## 3. Start the container

```powershell
docker compose up -d
```

## 4. Check container status

```powershell
docker compose ps
```

## 5. View startup logs

```powershell
docker compose logs -f app
```

## 6. Open the site

After the container starts successfully, open:

```text
http://localhost:9001
```

## 7. Verify Chinese locale files in the container

Enter the container:

```powershell
docker exec -it senaite-source-clean-2x bash
```

Check the locale directory:

```bash
ls /home/senaite/senaitelims/src/senaite.impress/src/senaite/impress/locales/zh_CN/LC_MESSAGES
```

You should see these two files:

```text
senaite.impress.mo
senaite.impress.po
```

Optionally inspect the PO file content:

```bash
head -n 20 /home/senaite/senaitelims/src/senaite.impress/src/senaite/impress/locales/zh_CN/LC_MESSAGES/senaite.impress.po
```

## 8. Stop the container

```powershell
docker compose down
```


