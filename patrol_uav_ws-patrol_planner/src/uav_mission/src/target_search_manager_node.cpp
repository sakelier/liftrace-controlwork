#include <ros/ros.h>

int main(int argc, char** argv)
{
    ros::init(argc, argv, "target_search_manager");

    ros::NodeHandle nh;
    ros::NodeHandle pnh("~");

    ROS_INFO("Target search manager C++ node started.");

    ros::spin();
    return 0;
}