import pytest
from PIL import Image, ImageChops

from purffle_shorts.media import MediaItem
from purffle_shorts.render import _compose_vertical_product_canvas, extract_frame, prepare_segment

from .conftest import needs_ffmpeg


def test_square_product_canvas_keeps_photo_centered_over_blurred_background(tmp_path):
    source = tmp_path / "square.jpg"
    Image.new("RGB", (500, 500), "white").save(source)
    Image.new("RGB", (220, 320), "red").save(tmp_path / "product.jpg")
    product = Image.open(tmp_path / "product.jpg")
    source_image = Image.new("RGB", (500, 500), "white")
    source_image.paste(product, (140, 90))
    source_image.save(source)

    framed = _compose_vertical_product_canvas(source, 360, 640, 0, tmp_path / "work")
    with Image.open(framed) as image:
        assert image.size == (360, 640)
        center = image.getpixel((180, 290))
        corner = image.getpixel((10, 10))
        assert center[0] > center[1] * 2  # red product remains visible at center
        assert corner != (255, 255, 255)  # catalogue white is replaced by a darkened backdrop
        assert ImageChops.difference(image, Image.new("RGB", image.size, corner)).getbbox()


@needs_ffmpeg
@pytest.mark.parametrize("ken_burns", [False, True])
def test_product_photo_fills_frame_without_an_inset_card(tmp_path, settings, ken_burns):
    source = tmp_path / "product.png"
    photo = Image.new("RGB", (500, 500), "white")
    photo.paste("red", (150, 0, 350, 500))
    photo.save(source)
    work = tmp_path / "work"
    work.mkdir()
    config = settings.with_overrides(resolution=(180, 320), fps=12, color_grade="none", ken_burns=ken_burns)
    item = MediaItem("product-page", "hero", "image", path=source)

    segment = prepare_segment(item, 0.5, 0, config, work)
    frame = extract_frame(segment, 0.1, tmp_path / "frame.jpg")
    with Image.open(frame) as image:
        assert image.size == config.resolution
        assert min(image.getpixel((5, 160))) > 220
        red, green, blue = image.getpixel((90, 160))
        assert red > 200 and green < 40 and blue < 40


@needs_ffmpeg
@pytest.mark.parametrize("ken_burns", [False, True])
def test_product_at_right_edge_stays_in_the_vertical_crop(tmp_path, settings, ken_burns):
    source = tmp_path / "product.png"
    photo = Image.new("RGB", (500, 500), "white")
    photo.paste("red", (350, 0, 450, 500))
    photo.save(source)
    work = tmp_path / "work"
    work.mkdir()
    config = settings.with_overrides(resolution=(180, 320), fps=12, color_grade="none", ken_burns=ken_burns)
    item = MediaItem("product-page", "hero", "image", path=source, extra={"focus_x": 0.8})

    segment = prepare_segment(item, 0.5, 0, config, work)
    frame = extract_frame(segment, 0.1, tmp_path / "frame.jpg")
    with Image.open(frame) as image:
        red, green, blue = image.getpixel((110, 160))
        assert red > 200 and green < 40 and blue < 40
