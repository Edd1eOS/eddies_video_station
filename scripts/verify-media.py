"""Developer smoke check. Run with the bundled engine's Python (PyAV/Pillow)."""
import sys
from pathlib import Path
import av

path=Path(sys.argv[1])
with av.open(str(path)) as video:
    stream=video.streams.video[0]
    count=0
    first=None
    for frame in video.decode(stream):
        if first is None: first=frame
        count+=1
    assert count>0,'No decodable frames'
    print(f'{path.name}: {count} frames, {stream.width}x{stream.height}, fps={stream.average_rate}')
    if len(sys.argv)>2:
        first.to_image().save(sys.argv[2])
