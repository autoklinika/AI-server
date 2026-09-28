from ai_bridge.benchmarks.resources import ResourcePoint, ResourceSampler


def test_resource_sampler_reports_system_peak_delta():
    points = iter([
        ResourcePoint(ram_used_bytes=100, vram_used_bytes=200),
        ResourcePoint(ram_used_bytes=150, vram_used_bytes=260),
        ResourcePoint(ram_used_bytes=120, vram_used_bytes=230),
    ])

    def reader():
        try:
            return next(points)
        except StopIteration:
            return ResourcePoint(ram_used_bytes=120, vram_used_bytes=230)

    sampler = ResourceSampler(interval_ms=1000, reader=reader).start()
    sampler._points.append(reader())
    usage = sampler.stop()

    assert usage.scope == "system"
    assert usage.baseline.ram_used_bytes == 100
    assert usage.peak.ram_used_bytes == 150
    assert usage.peak_delta_ram_bytes == 50
    assert usage.peak_delta_vram_bytes == 60
