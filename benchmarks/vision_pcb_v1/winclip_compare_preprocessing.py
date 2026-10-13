#!/usr/bin/env python3
"""Paired high-resolution tiling experiment with WinCLIP CPU on VisA.

Small balanced subsetting supported for cheap smoke; per-mode calibration
is required. No claim that image-level max pooling localizes defects.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
from PIL import Image
import torch
from torchvision.transforms.functional import pil_to_tensor
from anomalib.models.image.winclip.torch_model import WinClipModel, BACKBONE, PRETRAINED
from tile_policy import tile_rectangles,aggregate_max

def emit_immutable(path:Path,payload:str):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8')==payload: return
        raise FileExistsError(f"refusing overwrite: {path}")
    path.write_text(payload,encoding='utf-8')

def score(model,images,batch_size):
    scores=[]
    for start in range(0,len(images),batch_size):
        tensors=[pil_to_tensor(im).float()/255. for im in images[start:start+batch_size]]
        # Force uniform crop geometry within batch
        if any(t.shape != tensors[0].shape for t in tensors):raise ValueError("nonuniform tile tensor shapes")
        with torch.inference_mode():out=model(torch.stack(tensors))
        scores += [float(x) for x in out.pred_score.flatten().tolist()]
    if any(not 0<=x<=1 for x in scores):raise ValueError("invalid WinCLIP score")
    return scores

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--ground-truth',type=Path,required=True)
    p.add_argument('--image-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--per-label',type=int,default=2,help="0 = entire dataset, positive = cap each split/label")
    p.add_argument('--tile-size',type=int,default=640)
    p.add_argument('--overlap',type=float,default=.25)
    p.add_argument('--batch-size',type=int,default=2)
    args=p.parse_args()
    if args.per_label<0 or not 1<=args.batch_size<=4:raise ValueError("invalid per-label/batch-size")
    torch.set_num_threads(2)
    all_gt=[json.loads(x) for x in args.ground_truth.read_text().splitlines()]
    chosen=[]
    for split in ('train','calibration','holdout','challenge'):
        for label in (('normal',) if split=='train' else ('normal','anomaly')):
            sample=sorted((x for x in all_gt if x['split']==split and x['label']==label),key=lambda x:x['sample_id'])
            chosen.extend(sample[:args.per_label] if args.per_label else sample)
    chosen.sort(key=lambda x:x['sample_id'])
    gt_data=''.join(json.dumps(x,sort_keys=True,ensure_ascii=False)+'\n' for x in chosen)
    emit_immutable(args.output/'ground_truth.jsonl',gt_data)
    model=WinClipModel(class_name='printed circuit board',apply_transform=True).eval()
    preds={'global':{'calibration':[],'holdout':[],'challenge':[]},
           'tiled':{'calibration':[],'holdout':[],'challenge':[]}}
    details=[]
    start=time.monotonic()
    for j,r in enumerate(chosen):
        if r['split']=='train':continue
        image_file=(args.image_root/r['image_path']).resolve(strict=True)
        if not image_file.is_relative_to(args.image_root.resolve()):raise ValueError("unsafe image path")
        with Image.open(image_file) as img:
            original=img.convert('RGB')
            w,h=original.size
            global_score=score(model,[original],1)[0]
            rects=tile_rectangles(w,h,args.tile_size,args.overlap)
            crops=[original.crop(box) for box in rects]
            tile_scores=score(model,crops,args.batch_size)
            tiled_score=aggregate_max(global_score,tile_scores)
        split=r['split']
        for mode,value in [('global',global_score),('tiled',tiled_score)]:
            preds[mode][split].append({'sample_id':r['sample_id'],'model_id':'winclip',
                'image_score':value,'localization_mode':'none','regions':[]})
        details.append({'sample_id':r['sample_id'],'split':split,'n_tiles':len(rects),
            'global_score':global_score,'tile_scores':tile_scores,
            'tiled_max_score':tiled_score,'rectangles':rects})
        print('IMAGE',split,r['sample_id'],'n_tiles',len(rects),
              'global',round(global_score,5),'tiled',round(tiled_score,5),flush=True)
    for mode,per_split in preds.items():
        for split,values in per_split.items():
            payload=''.join(json.dumps(x,sort_keys=True)+'\n' for x in sorted(values,key=lambda x:x['sample_id']))
            emit_immutable(args.output/mode/f'winclip_{split}.jsonl',payload)
    emit_immutable(args.output/'tile_details.jsonl',''.join(json.dumps(x,sort_keys=True)+'\n' for x in details))
    meta={'status':'TILING_PAIRED_PILOT_NOT_PRODUCTION_BENCHMARK',
          'baseline_sha256':hashlib.sha256(args.ground_truth.read_bytes()).hexdigest(),
          'selected_gt_sha256':hashlib.sha256(gt_data.encode()).hexdigest(),
          'model_id':'winclip','backbone':BACKBONE,'pretrained':PRETRAINED,
          'prompt':'printed circuit board','device':'cpu','threads':2,
          'modes':['global','tiled'],'tiled_aggregation':'max(global_score, all_tile_scores)',
          'tile_size':args.tile_size,'overlap':args.overlap,'batch_size':args.batch_size,
          'sample_count':len(chosen),'evaluated_images':len(details),
          'elapsed_seconds':round(time.monotonic()-start,2),
          'restrictions':'No box localization. Calibration thresholds MUST be independent per mode.'}
    emit_immutable(args.output/'metadata.json',json.dumps(meta,indent=2)+'\n')
    print('WINCLIP_PAIRED_TILING=PASS',flush=True)

if __name__=='__main__': main()
