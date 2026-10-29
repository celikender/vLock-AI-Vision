"""One-person, mask-geometry rule; no cloud images or generated executable rules."""
import math


def valid_detection(detection):
    box, center = detection['bbox'], detection['center']
    values = list(box) + list(center)
    return (len(box) == 4 and len(center) == 2 and
            all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1 for v in values) and
            box[0] < box[2] and box[1] < box[3] and
            box[0] <= center[0] <= box[2] and box[1] <= center[1] <= box[3])


def inside(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def overlap(a,b):
    intersection = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0


class RaisedHands:
    def __init__(self):
        self.previous = None

    def reset(self):
        self.previous = None

    def evaluate(self, concepts):
        try:
            hands, heads, persons = (concepts[name] for name in ('hand','head','person'))
            if len(hands) != 2 or len(heads) != 1 or len(persons) != 1:
                raise ValueError()
            if not all(valid_detection(d) for d in hands + heads + persons):
                raise ValueError()
            head, person = heads[0], persons[0]
            if not all(inside(d['center'],person['bbox']) for d in hands + heads):
                raise ValueError()
        except (KeyError, TypeError, ValueError, IndexError):
            self.reset()
            return None, 'Need exactly one person, one head, and two associated hand masks; observation unknown.'
        # Entire hand mask must be above the top of the head, with a 1% margin.
        raised = all(d['bbox'][3] <= head['bbox'][1] - 0.01 for d in hands)
        if not raised:
            self.reset()
            return 0, 'Both hand masks are not entirely above the head.'
        # Relative centers reduce sensitivity to simple camera/person translation.
        points = [[d['center'][0]-head['center'][0], d['center'][1]-head['center'][1]] for d in hands]
        previous = self.previous
        self.previous = (points, person['bbox'])
        if previous is None or overlap(previous[1], person['bbox']) < 0.3:
            return None, 'Hands above head; collecting a consistent movement baseline.'
        old = previous[0]
        distances = min(([math.dist(old[0],points[0]),math.dist(old[1],points[1])],
                         [math.dist(old[0],points[1]),math.dist(old[1],points[0])]), key=sum)
        if any(d > 0.3 for d in distances):
            self.reset()
            return None, 'Hand correspondence changed too far; movement is unknown.'
        active = int(all(d >= 0.04 for d in distances))
        return active, ('Both hands above head and moving relative to it.' if active
                        else 'Hands above head; both are not moving enough.')
