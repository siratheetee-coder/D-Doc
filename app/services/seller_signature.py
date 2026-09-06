"""Private, persistent seller signing profile shared by sales documents and email."""
import io
import json
import uuid
from PIL import Image, ImageOps, ImageChops
from app.database import get_data_dir


def clean_signature(source):
    """Remove pale paper, including old uploads, and crop to visible ink."""
    image = ImageOps.exif_transpose(source).convert('RGBA')
    alpha = image.convert('L').point(lambda v: max(0, min(255, int((220-v)*255/40))))
    image.putalpha(ImageChops.darker(alpha, image.getchannel('A')))
    box = image.getchannel('A').point(lambda v: 255 if v >= 32 else 0).getbbox()
    if not box:
        raise ValueError('ไม่พบเส้นลายเซ็น')
    return image.crop(box)


def seller_profile(defaults):
    profile = dict(defaults)
    directory = get_data_dir() / 'seller-signature'
    try:
        saved = json.loads((directory / 'profile.json').read_text(encoding='utf-8'))
        profile['signer'] = str(saved.get('signer', profile.get('signer', '')))
        name = saved.get('image', '')
        if isinstance(name, str) and len(name) == 36 and name.endswith('.png') and all(c in '0123456789abcdef' for c in name[:-4]):
            path = directory / name
            if path.is_file():
                profile['signature_path'] = str(path)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return profile


def save_signature(signer, data=None, remove=False):
    directory = get_data_dir() / 'seller-signature'
    profile = seller_profile({})
    name = '' if remove else (profile.get('signature_path', '').replace('\\', '/').split('/')[-1])
    if data:
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('ไฟล์ต้องมีขนาดไม่เกิน 5 MB')
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 16000000:
                    raise ValueError()
                image = clean_signature(source)
            image.thumbnail((900, 360))
        except Exception as exc:
            raise ValueError('กรุณาใช้รูป PNG, JPEG หรือ WebP ที่มีเส้นลายเซ็นชัดเจน') from exc
        directory.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + '.png'
        image.save(directory / name, 'PNG')
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (uuid.uuid4().hex + '.json')
    temporary.write_text(json.dumps({'signer': signer.strip(), 'image': name}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(directory / 'profile.json')
