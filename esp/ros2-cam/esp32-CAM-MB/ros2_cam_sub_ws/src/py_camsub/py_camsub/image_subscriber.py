import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
"""
cd ros2_cam_sub_ws  # Navigate to your package directory
colcon build --packages-select py_camsub    # Build the package
source install/setup.bash  # Source the package setup script

"""

class ImageSubscriber(Node):
    def __init__(self):
        super().__init__('image_subscriber')
        self.subscription = self.create_subscription(
            Image,
            '/image/color/1',
            self.image_callback,
            10
        )
        self.cv_bridge = CvBridge()

    def image_callback(self, msg):
        # Convert ROS Image message to OpenCV image
        cv_image = self.cv_bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        # Process the image (e.g., display, save, or analyze)
        # Example: Display the image
        cv2.imshow('Image', cv_image)
        cv2.waitKey(1)

def main(args=None):
    rclpy.init(args=args)
    image_subscriber = ImageSubscriber()
    rclpy.spin(image_subscriber)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
