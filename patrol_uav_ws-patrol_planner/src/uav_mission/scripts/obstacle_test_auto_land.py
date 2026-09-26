#!/usr/bin/env python3
"""Test-only completed-mission handoff to an allowed PX4 mode."""
import json
import math
import threading
import rospy
from mavros_msgs.msg import State
from mavros_msgs.srv import SetMode
from nav_msgs.msg import Odometry
from std_msgs.msg import String


def mission_ready_to_land(status, start_mode, revision=''):
    common = (status.get('start_mode') == start_mode
              and bool(status.get('mission_id'))
              and status.get('phase') == 'LAND'
              and status.get('active_command') == 'LAND'
              and status.get('mission_failed') is False)
    if not common:
        return False
    if start_mode == 'full':
        return True
    return (start_mode == 'post_delivery'
            and status.get('post_delivery_route_revision') == revision
            and status.get('post_delivery_route_complete') is True)


def settled(odom, frame, xy, z, xy_tolerance, z_tolerance, max_speed):
    p, v = odom.pose.pose.position, odom.twist.twist.linear
    values = (p.x, p.y, p.z, v.x, v.y, v.z)
    return (odom.header.frame_id == frame
            and all(math.isfinite(x) for x in values)
            and math.hypot(p.x-xy[0], p.y-xy[1]) <= xy_tolerance
            and abs(p.z-z) <= z_tolerance
            and math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z) <= max_speed)


def configured_cruise_z(has_param, get_param):
    """Resolve one altitude authority while retaining older launch support."""
    if has_param('~cruise_z'):
        return float(get_param('~cruise_z'))
    parameter = get_param(
        '~cruise_z_param',
        '/navigation/mission_manager/mission/return_altitude')
    if not isinstance(parameter, str) or not parameter.startswith('/'):
        raise ValueError('invalid cruise altitude parameter name')
    return float(get_param(parameter))


class AutoLand:
    def __init__(self):
        self.frame = rospy.get_param('~frame', 'camera_init')
        self.xy = rospy.get_param('~landing_xy')
        self.z = configured_cruise_z(rospy.has_param, rospy.get_param)
        self.start_mode = rospy.get_param('~start_mode', 'post_delivery')
        self.revision = rospy.get_param('~route_revision', '')
        self.handoff_mode = str(rospy.get_param(
            '~handoff_mode', 'AUTO.LAND')).strip().upper()
        self.dwell = float(rospy.get_param('~settle_seconds', 1.0))
        self.xy_tol = float(rospy.get_param('~xy_tolerance', .18))
        self.z_tol = float(rospy.get_param('~z_tolerance', .15))
        self.speed = float(rospy.get_param('~max_speed', .12))
        if (not self.frame or self.start_mode not in ('full', 'post_delivery')
                or self.handoff_mode not in ('AUTO.LAND', 'POSCTL')
                or (self.start_mode == 'post_delivery' and not self.revision)
                or len(self.xy) != 2
                or not all(math.isfinite(float(v)) for v in
                           list(self.xy)+[self.z, self.dwell, self.xy_tol, self.z_tol, self.speed])
                or min(self.dwell, self.xy_tol, self.z_tol, self.speed) <= 0):
            raise ValueError('invalid test landing parameters')
        self.lock = threading.RLock()
        self.status, self.state, self.odom = {}, None, None
        self.status_at = self.state_at = 0.0
        self.since = None
        self.attempts, self.last_attempt = 0, 0.0
        self.handed_over = False
        self.mode = rospy.ServiceProxy(rospy.get_param('~set_mode_service', '/mavros/set_mode'), SetMode)
        self.subs = [
            rospy.Subscriber(rospy.get_param('~status_topic', '/navigation/mission_status'), String, self.on_status, queue_size=1),
            rospy.Subscriber(rospy.get_param('~state_topic', '/mavros/state'), State, self.on_state, queue_size=1),
            rospy.Subscriber(rospy.get_param('~odom_topic', '/navigation/local_odom'), Odometry, self.on_odom, queue_size=1),
        ]
        self.timer = rospy.Timer(rospy.Duration(.1), self.tick)

    def on_status(self, msg):
        with self.lock:
            try:
                value = json.loads(msg.data)
                self.status = value if isinstance(value, dict) else {}
            except ValueError:
                self.status = {}
            self.status_at = rospy.Time.now().to_sec()

    def on_state(self, msg):
        with self.lock:
            self.state = msg
            self.state_at = rospy.Time.now().to_sec()

    def on_odom(self, msg):
        with self.lock:
            self.odom = msg

    def tick(self, _event):
        with self.lock:
            now = rospy.Time.now().to_sec()
            if self.handed_over or self.attempts >= 3:
                return
            # Only request from OFFBOARD; never counter a pilot's mode takeover.
            valid = (mission_ready_to_land(
                         self.status, self.start_mode, self.revision)
                     and 0 <= now-self.status_at <= 15.0
                     and self.state is not None and self.state.connected
                     and self.state.armed and self.state.mode == 'OFFBOARD'
                     and 0 <= now-self.state_at <= 2.0
                     and self.odom is not None
                     and -.05 <= now-self.odom.header.stamp.to_sec() <= .5
                     and settled(self.odom, self.frame, self.xy, self.z,
                                 self.xy_tol, self.z_tol, self.speed))
            if not valid:
                self.since = None
                return
            if self.since is None:
                self.since = now
            if now-self.since < self.dwell or now-self.last_attempt < 2.0:
                return
            self.attempts += 1
            self.last_attempt = now
            try:
                response = self.mode(
                    base_mode=0, custom_mode=self.handoff_mode)
                self.handed_over = bool(response.mode_sent)
                rospy.logwarn(
                    'Mission test %s handoff request %d accepted=%s; '
                    'check MAVROS mode and pilot control',
                    self.handoff_mode, self.attempts, self.handed_over)
            except rospy.ServiceException as error:
                rospy.logerr('Mission test %s handoff request failed: %s',
                             self.handoff_mode, error)


if __name__ == '__main__':
    rospy.init_node('obstacle_test_auto_land')
    AutoLand()
    rospy.spin()
