"""Exercise quote handling without downloading private QQ media."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location('ddl_images', Path(__file__).resolve().parents[1] / 'integrations/astrbot_plugin_ddl/images.py')
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


class Image:
    def __init__(self, reference):
        self.url = reference
        self.file = ''
        self.convert_to_file_path = AsyncMock(return_value='/tmp/' + reference)


class Reply:
    def __init__(self, chain=None, sender_id='1000000002'):
        self.chain = chain
        self.sender_id = sender_id


class QQImageTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, components):
        return await images.collect_images(components, image_type=Image, reply_type=Reply,
                                           sender_id='1000000002', bot_id='123456')

    async def test_direct_and_quoted_images_reach_model_inputs(self):
        direct, quoted = Image('direct'), Image('quoted')
        self.assertEqual(await self.collect([direct, Reply([quoted])]), ['/tmp/direct', '/tmp/quoted'])

    async def test_quoted_only_and_bot_quotes(self):
        self.assertEqual(await self.collect([Reply([Image('schedule')])]), ['/tmp/schedule'])
        self.assertEqual(await self.collect([Reply([Image('bot')], '123456')]), ['/tmp/bot'])

    async def test_duplicates_download_once(self):
        image = Image('same')
        self.assertEqual(await self.collect([image, Reply([image, Image('same')])]), ['/tmp/same'])
        image.convert_to_file_path.assert_awaited_once()

    async def test_more_than_three_rejected_before_download(self):
        parts = [Image(str(i)) for i in range(4)]
        with self.assertRaisesRegex(ValueError, '最多识别3张'):
            await self.collect([Reply(parts)])
        for item in parts:
            item.convert_to_file_path.assert_not_awaited()

    async def test_unavailable_quote_or_download_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, '被引用的原图'):
            await self.collect([Reply()])
        image = Image('expired')
        image.convert_to_file_path.side_effect = OSError('private URL must not appear')
        with self.assertRaisesRegex(ValueError, '图片下载失败') as error:
            await self.collect([image])
        self.assertNotIn('private URL', str(error.exception))

    async def test_foreign_or_nested_quotes_are_not_read(self):
        self.assertEqual(await self.collect([Reply([Image('other')], '1000000001')]), [])
        self.assertEqual(await self.collect([Reply([Reply([Image('nested')])])]), [])
        self.assertEqual(await self.collect([SimpleNamespace(text='query')]), [])

    async def test_current_image_still_works_if_quote_unavailable(self):
        self.assertEqual(await self.collect([Reply(), Image('current')]), ['/tmp/current'])
