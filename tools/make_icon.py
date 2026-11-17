import os
from PIL import Image, ImageDraw, ImageFont

W = 256
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, W - 8, W - 8], radius=48, fill=(19, 42, 74, 255))
# 左侧装饰条
d.rounded_rectangle([28, 66, 44, 190], radius=8, fill=(22, 119, 255, 255))
try:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 92)
except Exception:
    font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 92)
text = "FIX"
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((W - tw) / 2 + 14 - bbox[0], (W - th) / 2 - bbox[1] - 2), text, font=font, fill=(255, 255, 255, 255))
os.makedirs("assets", exist_ok=True)
img.save("assets/app.png")
img.save("assets/app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon ok")
