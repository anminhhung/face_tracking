# vim: expandtab:ts=4:sw=4
import cv2
from shapely.geometry import Point, Polygon, shape, box

class TrackState:
    """
    Enumeration type for the single target track state. Newly created tracks are
    classified as `tentative` until enough evidence has been collected. Then,
    the track state is changed to `confirmed`. Tracks that are no longer alive
    are classified as `deleted` to mark them for removal from the set of active
    tracks.

    """

    Tentative = 1
    Confirmed = 2
    Deleted = 3


class Track:
    """
    A single target track with state space `(x, y, a, h)` and associated
    velocities, where `(x, y)` is the center of the bounding box, `a` is the
    aspect ratio and `h` is the height.

    Parameters
    ----------
    mean : ndarray
        Mean vector of the initial state distribution.
    covariance : ndarray
        Covariance matrix of the initial state distribution.
    track_id : int
        A unique track identifier.
    n_init : int
        Number of consecutive detections before the track is confirmed. The
        track state is set to `Deleted` if a miss occurs within the first
        `n_init` frames.
    max_age : int
        The maximum number of consecutive misses before the track state is
        set to `Deleted`.
    feature : Optional[ndarray]
        Feature vector of the detection this track originates from. If not None,
        this feature is added to the `features` cache.

    Attributes
    ----------
    mean : ndarray
        Mean vector of the initial state distribution.
    covariance : ndarray
        Covariance matrix of the initial state distribution.
    track_id : int
        A unique track identifier.
    hits : int
        Total number of measurement updates.
    age : int
        Total number of frames since first occurance.
    time_since_update : int
        Total number of frames since last measurement update.
    state : TrackState
        The current track state.
    features : List[ndarray]
        A cache of features. On each measurement update, the associated feature
        vector is added to this list.

    """

    def __init__(self, cfg, mean, covariance, track_id, n_init, max_age,
                 det_confidence, det_class, det_best_bbox, feature=None):
        self.cfg = cfg
        self.mean = mean
        self.covariance = covariance
        self.track_id = track_id
        self.hits = 1
        self.age = 1
        self.time_since_update = 0

        self.det_confidence = det_confidence
        self.det_class = det_class
        self.det_best_bbox = det_best_bbox

        self.state = TrackState.Tentative
        self.features = []
        if feature is not None:
            self.features.append(feature)

        self._n_init = n_init
        self._max_age = max_age
        self.track_line = []

    def check_in_polygon(self, center_point, polygon):
        pts = Point(center_point[0], center_point[1])
        if polygon.contains(pts):
            return True
        return False
    
    # def area_intersect(self, bbox):
    #     ROI = Polygon(self.cfg.CAM.ROI_DEFAULT)
    #     obj_poly = box(minx=int(bbox[0]), miny=int(bbox[1]), maxx=int(bbox[2]), maxy=int(bbox[3]))
    #     obj_area = obj_poly.area
    #     intersect_area_scale = ROI.intersection(obj_poly).area / obj_area
    #     return intersect_area_scale

    def to_tlwh(self):
        """Get current position in bounding box format `(top left x, top left y,
        width, height)`.

        Returns
        -------
        ndarray
            The bounding box.

        """
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    def to_tlbr(self):
        """Get current position in bounding box format `(min x, miny, max x,
        max y)`.

        Returns
        -------
        ndarray
            The bounding box.

        """
        ret = self.to_tlwh()
        ret[2:] = ret[:2] + ret[2:]
        return ret

    def predict(self, kf):
        """Propagate the state distribution to the current time step using a
        Kalman filter prediction step.

        Parameters
        ----------
        kf : kalman_filter.KalmanFilter
            The Kalman filter.

        """
        self.mean, self.covariance = kf.predict(self.mean, self.covariance)
        self.age += 1
        self.time_since_update += 1

    def update(self, kf, detection):
        """Perform Kalman filter measurement update step and update the feature
        cache.

        Parameters
        ----------
        kf : kalman_filter.KalmanFilter
            The Kalman filter.
        detection : Detection
            The associated detection.

        """
        self.mean, self.covariance = kf.update(
            self.mean, self.covariance, detection.to_xyah())
        self.features.append(detection.feature)

        # if detection.confidence > self.det_confidence:
        #     self.det_confidence = detection.confidence
        #     self.det_class = detection.cls
        #     self.det_best_bbox = detection.to_tlbr()
        
        # x,y,w,h = self.to_tlwh()
        # center_x = int(x+w/2)
        # center_y = int(y+h/2)
        # self.track_line.append([center_x,center_y])
        self.hits += 1
        self.time_since_update = 0

        # x,y,w,h = detection.tlwh
        # centroid_x = int(x+w/2)
        # centroid_y = int(y+h/2)
        # area_intersect = self.area_intersect(detection.to_tlbr())
        # if self.check_in_polygon((centroid_x, centroid_y), Polygon(self.cfg.CAM.ROI_DEFAULT)) == False and self.state == TrackState.Tentative:
        #     self.state =TrackState.Deleted
        # if area_intersect < 0.01 and self.state == TrackState.Tentative:
        #     self.state =TrackState.Deleted
        if self.state == TrackState.Tentative and self.hits >= self._n_init:
            self.state = TrackState.Confirmed
        
        
    def mark_missed(self):
        """Mark this track as missed (no association at the current time step).
        """
        if self.state == TrackState.Tentative:
            self.state = TrackState.Deleted
        elif self.time_since_update > self._max_age:
            self.state = TrackState.Deleted

    def is_tentative(self):
        """Returns True if this track is tentative (unconfirmed).
        """
        return self.state == TrackState.Tentative

    def is_confirmed(self):
        """Returns True if this track is confirmed."""
        return self.state == TrackState.Confirmed

    def is_deleted(self):
        """Returns True if this track is dead and should be deleted."""
        return self.state == TrackState.Deleted

    def delete(self):
        self.state = TrackState.Deleted

    def draw_track_line(self,image):
        if len(self.track_line) > 1:
          for i in range(len(self.track_line)-1):
            p1 = self.track_line[i+1]
            p2 = self.track_line[i]
            image = cv2.line(image, (p1[0], p1[1]), (p2[0], p2[1]), (255,255,0), 2)
        return image