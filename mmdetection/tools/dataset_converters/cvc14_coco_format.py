import argparse
import copy
import os.path as osp
from glob import glob
import numpy as np
import os
import warnings

import mmcv
from PIL import Image
import xml.etree.ElementTree as ET

''''
LWIR和VISIBLE共享同一套Annotations
该代码根据Annotations从文件中索引LWIR的图片，并根据路径索引相匹配的VISIBLE图片
最后只保存LWIR的json文件，即coco['file_name'] = path/to/lwir/image
在mmdetection/mmdet/datasets/pipelines/my_load_rgbt_pipeline.py中，我根据file_name索引lwir image，并匹配相应的visible图片
'''


label_ids = {'person': 0, 'people': 1, 'person?': 2, 'person?a': 3}


def parse_xml(args):
    xml_path, img_path = args
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size = root.find('size')
    w = int(size.find('width').text)
    h = int(size.find('height').text)
    bboxes = []
    labels = []
    bboxes_ignore = []
    labels_ignore = []
    for obj in root.findall('object'):
        name = obj.find('name').text
        label = label_ids[name]
        difficult = int(obj.find('difficult').text)
        bnd_box = obj.find('bndbox')
        bbox = [
            int(bnd_box.find('xmin').text),
            int(bnd_box.find('ymin').text),
            int(bnd_box.find('xmax').text),
            int(bnd_box.find('ymax').text)
        ]
        if difficult or not name == 'person':
            bboxes_ignore.append(bbox)
            labels_ignore.append(label)
        else:
            bboxes.append(bbox)
            labels.append(label)
    if not bboxes:
        bboxes = np.zeros((0, 4))
        labels = np.zeros((0, ))
    else:
        bboxes = np.array(bboxes, ndmin=2) - 1
        labels = np.array(labels)
    if not bboxes_ignore:
        bboxes_ignore = np.zeros((0, 4))
        labels_ignore = np.zeros((0, ))
    else:
        bboxes_ignore = np.array(bboxes_ignore, ndmin=2) - 1
        labels_ignore = np.array(labels_ignore)
    annotation = {
        'filename': img_path,
        'width': w,
        'height': h,
        'ann': {
            'bboxes': bboxes.astype(np.float32),
            'labels': labels.astype(np.int64),
            'bboxes_ignore': bboxes_ignore.astype(np.float32),
            'labels_ignore': labels_ignore.astype(np.int64)
        }
    }
    return annotation


def cvt_annotations(cvc14_path, dataset_name, split, out_file):
    img_paths = sorted(glob(osp.join(cvc14_path, 'images', dataset_name, '*.png')))
    xml_paths = [
        osp.join(cvc14_path, 'labels', split, osp.basename(img_name).replace('.png', '.xml'))
        for img_name in img_paths
    ]

    if split == 'train':
        assert len(img_paths) == len(xml_paths) == 4823
    elif split == 'test':
        assert len(img_paths) == len(xml_paths) == 1195

    annotations = mmcv.track_progress(parse_xml,
                                           list(zip(xml_paths, img_paths)))
    if out_file.endswith('json'):
        annotations = cvt_to_coco_json(annotations)
    mmcv.dump(annotations, out_file)
    return annotations


def cvt_to_coco_json(annotations):
    image_id = 0
    annotation_id = 0
    coco = dict()
    coco['images'] = []
    coco['type'] = 'instance'
    coco['categories'] = []
    coco['annotations'] = []
    image_set = set()

    def addAnnItem(annotation_id, image_id, category_id, bbox, difficult_flag):
        annotation_item = dict()
        annotation_item['segmentation'] = []

        seg = []
        # bbox[] is x1,y1,x2,y2
        # left_top
        seg.append(int(bbox[0]))
        seg.append(int(bbox[1]))
        # left_bottom
        seg.append(int(bbox[0]))
        seg.append(int(bbox[3]))
        # right_bottom
        seg.append(int(bbox[2]))
        seg.append(int(bbox[3]))
        # right_top
        seg.append(int(bbox[2]))
        seg.append(int(bbox[1]))

        annotation_item['segmentation'].append(seg)

        xywh = np.array(
            [bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]])
        annotation_item['area'] = int(xywh[2] * xywh[3])
        if difficult_flag == 1:
            annotation_item['ignore'] = 0
            annotation_item['iscrowd'] = 1
        else:
            annotation_item['ignore'] = 0
            annotation_item['iscrowd'] = 0
        annotation_item['image_id'] = int(image_id)
        annotation_item['bbox'] = xywh.astype(int).tolist()
        annotation_item['category_id'] = int(category_id)
        annotation_item['id'] = int(annotation_id)
        coco['annotations'].append(annotation_item)
        return annotation_id + 1

    for category_id, name in enumerate(list(label_ids.keys())):
        category_item = dict()
        category_item['supercategory'] = str('none')
        category_item['id'] = int(category_id)
        category_item['name'] = str(name)
        coco['categories'].append(category_item)

    for ann_dict in annotations:
        file_name = ann_dict['filename']
        ann = ann_dict['ann']
        assert file_name not in image_set
        image_item = dict()
        image_item['id'] = int(image_id)
        image_item['file_name'] = str(file_name)
        image_item['height'] = int(ann_dict['height'])
        image_item['width'] = int(ann_dict['width'])
        coco['images'].append(image_item)
        image_set.add(file_name)

        bboxes = ann['bboxes'][:, :4]
        labels = ann['labels']
        for bbox_id in range(len(bboxes)):
            bbox = bboxes[bbox_id]
            label = labels[bbox_id]
            annotation_id = addAnnItem(
                annotation_id, image_id, label, bbox, difficult_flag=0)

        bboxes_ignore = ann['bboxes_ignore'][:, :4]
        labels_ignore = ann['labels_ignore']
        for bbox_id in range(len(bboxes_ignore)):
            bbox = bboxes_ignore[bbox_id]
            label = labels_ignore[bbox_id]
            annotation_id = addAnnItem(
                annotation_id, image_id, label, bbox, difficult_flag=1)

        image_id += 1

    return coco


def parse_args():
    parser = argparse.ArgumentParser(
        description='Convert CVC14 annotations to mmdetection format')
    parser.add_argument('--cvc14_path', default='/home/zx/cross-modality-det/datasets/cvc14',
                        help='CVC14 path')
    parser.add_argument('--out-dir', default='/home/zx/cross-modality-det/datasets/cvc14/coco_format',
                        help='output path')
    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    cvc14_path = args.cvc14_path
    out_dir = args.out_dir
    mmcv.mkdir_or_exist(out_dir)

    for split in ['train', 'test']:
        dataset_name = osp.join(split, 'lwir')
        print(f'processing {dataset_name} ...')
        cvt_annotations(cvc14_path, dataset_name, split,
                        osp.join(out_dir, f'lwir_{split}.json'))
    print('Done!')

if __name__ == '__main__':
    main()