"""Collect current and quoted images without crossing private conversations."""

import asyncio


async def collect_images(components, *, image_type, reply_type, sender_id, bot_id):
    candidates = []
    missing_quote = False
    for item in components:
        if isinstance(item, image_type):
            candidates.append(item)
        elif isinstance(item, reply_type):
            # AstrBot resolves OneBot replies into a chain. Read one level only;
            # nested replies must not pull unrelated messages into this request.
            chain = item.chain or []
            owner = str(item.sender_id or "")
            if not chain:
                missing_quote = True
            elif owner in {str(sender_id), str(bot_id)}:
                candidates.extend(part for part in chain if isinstance(part, image_type))

    images = []
    seen = set()
    for item in candidates:
        reference = item.url or item.file
        if not reference:
            raise ValueError("图片地址不可用，请重新发送原图。")
        if reference not in seen:
            seen.add(reference)
            images.append(item)
    if len(images) > 3:
        raise ValueError("每次最多识别3张图片，请分批发送。")
    if not images and missing_quote:
        raise ValueError("无法读取被引用的原图，请重新发送图片，并在同一条消息附上 /日程 指令。")
    try:
        return [await asyncio.wait_for(item.convert_to_file_path(), timeout=30) for item in images]
    except Exception as error:
        raise ValueError("图片下载失败或已过期，请重新发送原图后再试。") from error
