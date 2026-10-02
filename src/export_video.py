"""Silent video concatenation using PyAV already included in the engine runtime."""
import json
import sys
from fractions import Fraction
import av
import numpy as np


def concatenate(files, output, width=832, height=480, fps=24):
    count=0
    elapsed=0.0
    with av.open(output,'w') as container:
        stream=container.add_stream('libx264',rate=fps)
        stream.width=width; stream.height=height; stream.pix_fmt='yuv420p'
        stream.options={'crf':'20','preset':'fast'}
        for path in files:
            with av.open(path) as source:
                video=source.streams.video[0]
                rate=float(video.average_rate or fps)
                for frame in source.decode(video):
                    scale=min(width/frame.width,height/frame.height)
                    w=max(2,int(frame.width*scale)//2*2)
                    h=max(2,int(frame.height*scale)//2*2)
                    pixels=frame.reformat(width=w,height=h,format='rgb24').to_ndarray()
                    canvas=np.zeros((height,width,3),dtype=np.uint8)
                    x=(width-w)//2; y=(height-h)//2
                    canvas[y:y+h,x:x+w]=pixels
                    elapsed+=1/rate
                    while count<round(elapsed*fps):
                        out=av.VideoFrame.from_ndarray(canvas,format='rgb24')
                        out.pts=count; out.time_base=Fraction(1,fps)
                        for packet in stream.encode(out): container.mux(packet)
                        count+=1
        for packet in stream.encode(): container.mux(packet)
    if not count: raise ValueError('没有可合并的视频帧')
    return count


if __name__=='__main__':
    args=json.load(sys.stdin)
    print(concatenate(args['files'],args['output']))
