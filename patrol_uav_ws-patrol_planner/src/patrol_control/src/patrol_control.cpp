/**
 *  @file patrol_control.cpp
 *  @author luli (luli.gptt@gmail.com)
 *  @brief 本程序为无人机巡检流程控制程序，可以修改指定yaml，修改路径点
 *  @version 0.2
 *  @date 5-16-2025
 */
#include "patrol_control/patrol_control.h"
#include <tf/transform_listener.h>
#include "tf2_ros/transform_broadcaster.h"
#include <Eigen/Core>
#include <Eigen/Geometry>
#include "tf2_ros/transform_listener.h"
#include "tf2_ros/buffer.h"
#include "tf2_geometry_msgs/tf2_geometry_msgs.h" 
#include <yaml-cpp/yaml.h>

int times_detect = 0;  
bool flag_takeoff_done = 0;

// for detect
bool first_call = true;
bool have_planner_cmd = false, flag_land = false, have_waypoint_mark = false, have_land_mark = false;
ros::Time start_time;

geometry_msgs::PoseStamped uav_pose;
geometry_msgs::PoseStamped last_mavros_point_cmd;
//for take off
Eigen::Vector3f takeoff_point;

//last and now pub point
Eigen::Vector3f last_pub_point={0,0,0};
Eigen::Vector3f now_pub_point;

/** newest position **/
Eigen::Vector3f uav_newest_position;
/** used to save the adjustment target position **/
Eigen::Vector4f adjust_target_position;


namespace patrol_control {

LLController::LLController(ros::NodeHandle nh):nh_(nh) {   
    initializeNode();
    
    // 默认禁用圆形检测
    std_msgs::Bool detect_disable_msg;
    detect_disable_msg.data = false;
    detect_control_pub_.publish(detect_disable_msg);
    
    std::cout << "\033[47;30m ---------------------------------- Start mission ---------------------------------- \033[0m" << std::endl;
}
LLController::~LLController(){}


// 读取航路点，订阅无人机位置、圆环中心，发布目标点、投递装置动作指令
void LLController::initializeNode() {

    load_params();

    waypoint_now = -1;
    waypoint_next = 0;

    // 订阅无人机当前位置
    pose_sub_ = nh_.subscribe<const geometry_msgs::PoseStamped&>("/mavros/local_position/pose", 1,&LLController::positionCallback, this);
    fastplanner_cmd_sub_ = nh_.subscribe<const geometry_msgs::PoseStamped&>("/fastplanner/setpoint_position/local", 1,&LLController::plannercmdCallback, this);
    mavros_point_cmd_pub = nh_.advertise<geometry_msgs::PoseStamped>("/mavros/setpoint_position/local", 50);//px4 直接接收
    detect_sub_ = nh_.subscribe<const geometry_msgs::PoseStamped&>("/detect/waypoint_mark", 1,&LLController::waypointMarkCallback, this);
    land_mark_sub_ = nh_.subscribe<const geometry_msgs::PoseStamped&>("/detect/land_mark", 1,&LLController::landMarkCallback, this);
    land_client = nh_.serviceClient<mavros_msgs::CommandLong>("/mavros/cmd/command");
    servo_marky_sub_ = nh_.subscribe<const std_msgs::Bool&>("/detect/servo_complete", 1,&LLController::servoMarkyCallback, this);
    servo_status_pub_ = nh_.advertise<std_msgs::Bool>("/detect/servo_status", 1);
    //send goal to planner
    //setplanner_goal_pub_ = nh_.advertise<geometry_msgs::PoseStamped>("/planner_planner/goal_position", 1);
    setplanner_goal_pub_ = nh_.advertise<geometry_msgs::PoseStamped>("/fastplanner/goal", 1);
    servo_control_pub_ = nh_.advertise<std_msgs::Bool>("/detect/servo_control", 1);
    // 设置px4工作模式 land 
    set_mode_client = nh_.serviceClient<mavros_msgs::SetMode>("mavros/set_mode");
    cmd_timer = nh_.createTimer(ros::Duration(0.05), &LLController::cmdCallback, this);
    
    // 发布检测控制话题
    detect_control_pub_ = nh_.advertise<std_msgs::Bool>("/detect/control", 1);
    
    // 初始化舵机控制发布器
    servo1_pub_ = nh_.advertise<std_msgs::Bool>("/control1", 1);
    servo2_pub_ = nh_.advertise<std_msgs::Bool>("/control2", 1);
    servo3_pub_ = nh_.advertise<std_msgs::Bool>("/control3", 1);
    
    // 订阅对准反馈话题（从 alignment_control_converter 获取像素偏差）
    alignment_feedback_sub_ = nh_.subscribe<geometry_msgs::Point>("/detect/pixel_offset", 1, &LLController::alignmentFeedbackCallback, this);
    
    // 十字检测相关订阅者和发布者
    cross_pixel_offset_sub_ = nh_.subscribe<geometry_msgs::Point>("/detect/cross_pixel_offset", 1, &LLController::crossPixelOffsetCallback, this);
    cross_center_sub_ = nh_.subscribe<geometry_msgs::Point>("/detect/cross_center", 1, &LLController::crossCenterCallback, this);
    cross_status_sub_ = nh_.subscribe<std_msgs::Bool>("/detect/cross_status", 1, &LLController::crossStatusCallback, this);
    cross_control_pub_ = nh_.advertise<std_msgs::Bool>("/detect/cross_control", 1);
    
    // 初始化投递相关变量
    detect_point_counter = 0;
    drop_condition_met = false;
    current_pixel_error = 1000.0;
    descent_completed = false;
    final_target_height = 0.0;
    last_target_height_ = 0.0;
    last_check_time_ = ros::Time::now();
    
    // 确保drop_enabled已经从参数中加载
    if (!drop_enabled) {
        ROS_WARN("\033[33m[DropSystem] Drop system is disabled in configuration\033[0m");
    }
    
    // 根据配置的航路点数量初始化投递完成状态
    int detect_point_count = 0;
    for (const auto& wp : waypoint_list) {
        if (wp.pointmode == "Detect_point") {
            detect_point_count++;
        }
    }
    drop_completed.resize(detect_point_count, false);
    
    ROS_INFO("\033[32m[DropSystem] Initialized drop system for %d detect points\033[0m", detect_point_count);
    ROS_INFO("\033[36m[PatrolControl] Cross detection interface initialized\033[0m");
}

void LLController::positionCallback(const geometry_msgs::PoseStamped& msg) {
    uav_pose = msg;
    uav_newest_position = LLController::toEigen(msg.pose.position);  
    // 主函数
    if(!flag_takeoff_done){
        if(debug) ROS_INFO_THROTTLE(1, "\033[34mDistance with Next Waypoint =  %3lf m \033[0m ", (uav_newest_position - takeoff_point).norm());

        if((uav_newest_position - takeoff_point).norm() < takeoff_threshould){
            flag_takeoff_done = 1;
            NextPoint();
            Drone_mode = Run_point;}
    }
    else{
        // run point
        patrol();}
}

void LLController::patrol(){
    geometry_msgs::PoseStamped next_position_msg;
    float dis_to_next_position = 0;// diostance with next goal
    double yaw;
    //this flag is to adjust: run waypoint or circle adjust or landing 
    //to select next position
    switch(Drone_mode) {
        case Run_point:  // 前往waypoint_list_中的下一个航路点
            // 计算与目标点的距离
            dis_to_next_position = distance3d(uav_newest_position[0], uav_newest_position[1], uav_newest_position[2], 
            waypoint_list[waypoint_next].x ,waypoint_list[waypoint_next].y, waypoint_list[waypoint_next].z);

            next_position_msg.pose.position.x = waypoint_list[waypoint_next].x;
            next_position_msg.pose.position.y = waypoint_list[waypoint_next].y;
            next_position_msg.pose.position.z = waypoint_list[waypoint_next].z;
            yaw = waypoint_list[waypoint_next].yaw;
            next_position_msg.pose.orientation = tf::createQuaternionMsgFromYaw(yaw);

            arrive_goal_threshould = waypoint_threshould;//走点模式阈值为waypoint_threshould
            pub_goal(next_position_msg); //发送目标点给fastplanner或者直接给mavros
            break;

        case Hover:   // 悬停状态
            // 保持当前位置和姿态
            next_position_msg.pose.position.x = waypoint_list[waypoint_next].x;
            next_position_msg.pose.position.y = waypoint_list[waypoint_next].y;
            next_position_msg.pose.position.z = waypoint_list[waypoint_next].z;
            yaw = waypoint_list[waypoint_next].yaw;
            next_position_msg.pose.orientation = tf::createQuaternionMsgFromYaw(yaw);
            
            pub_goal(next_position_msg); //发送目标点给fastplanner或者直接给mavros
            break;

        case Aligning:   // 位置调整 
            // 计算与目标点的距离
            dis_to_next_position = distance3d(uav_newest_position[0], uav_newest_position[1], uav_newest_position[2],
            adjust_target_position[0],adjust_target_position[1], adjust_target_position[2]);

            patrol_cmd.pose.position.x = adjust_target_position[0];
            patrol_cmd.pose.position.y = adjust_target_position[1];
            patrol_cmd.pose.position.z = adjust_target_position[2];

            if (std::isnan(adjust_target_position[3])) yaw = waypoint_list[waypoint_next].yaw;
            else yaw = adjust_target_position[3];
            patrol_cmd.pose.orientation = tf::createQuaternionMsgFromYaw(yaw);
            arrive_goal_threshould = aligning_threshould;//走点模式阈值为waypoint_threshould
            break;

        case Land:   // 降落
            // 计算与目标点的距离
            dis_to_next_position = distance3d(uav_newest_position[0], uav_newest_position[1], 0,
            adjust_target_position[0], adjust_target_position[1], 0);

            patrol_cmd.pose.position.x = adjust_target_position[0];
            patrol_cmd.pose.position.y = adjust_target_position[1];
            patrol_cmd.pose.position.z = land_height;
            // 判断检测得到的yaw是否有效
            if (std::isnan(adjust_target_position[3])) yaw = waypoint_list[waypoint_next].yaw;
            else yaw = adjust_target_position[3];
            patrol_cmd.pose.orientation = tf::createQuaternionMsgFromYaw(yaw);

            if(flag_landing_detect)arrive_goal_threshould = landing_threshould;//降落模式如果要求对准，阈值为landing_threshould
            else arrive_goal_threshould = waypoint_threshould;//降落模式如果不要求对准，阈值为waypoint_threshould
            break;

        default:
            ROS_INFO_THROTTLE(1, "\033[31m[Error]: unknow  Drone_mode \033[0m ");
            break;
    }
    if(debug&&!flag_land) ROS_INFO_THROTTLE(1, "\033[34mDistance with Next Waypoint =  %3lf m\033[0m", dis_to_next_position);
    if(debug&&flag_land)  ROS_INFO_THROTTLE(1, "\033[34mHave Land!\033[0m ");
    double current_yaw = tf::getYaw(uav_pose.pose.orientation);
    //arrive goal position
    if (dis_to_next_position <= arrive_goal_threshould&& abs(current_yaw - yaw) <= arrive_yaw_threshould){
        switch (Point_mode)
        {
            case Detect_point:{  // Detect
                if (current_task_type == MAIN_MISSION) {
                    // 无论是否完成十字投递，都可以进行圆环检测
                    ROS_INFO_THROTTLE(5, "\033[34marrive waypoint, and detect... \033[0m ");
                    
                    // 启用圆形检测
                    std_msgs::Bool detect_enable_msg;
                    detect_enable_msg.data = true;
                    detect_control_pub_.publish(detect_enable_msg);
                    
                    // 如果已经完成十字投递，确保十字检测系统保持关闭
                    if (cross_drop_completed) {
                        std_msgs::Bool cross_disable_msg;
                        cross_disable_msg.data = false;
                        cross_control_pub_.publish(cross_disable_msg);
                        ROS_INFO("\033[36m[PatrolControl] Circle detection enabled, cross detection remains disabled\033[0m");
                    }
                    
                    Drone_mode= Aligning;
                    // 如果该点调整结束，切到下一个路点
                    if (WayPointDetectDone()){   
                        // 禁用圆形检测
                        std_msgs::Bool detect_disable_msg;
                        detect_disable_msg.data = false;
                        detect_control_pub_.publish(detect_disable_msg);
      
                        NextPoint();            

                        waypoint_mark111.pose.position.x = waypoint_mark.pose.position.x;
                        waypoint_mark111.pose.position.y = waypoint_mark.pose.position.y;
                        waypoint_mark111.pose.position.z = waypoint_mark.pose.position.z;
                        waypoint_mark111.pose.orientation = waypoint_mark.pose.orientation;
                        times_detect = 0;
                        have_waypoint_mark = false;
                        Drone_mode= Run_point;
                    }
                }
                // 移除十字任务处理逻辑，因为它不应该在Detect_point中处理
            break;}

            case Nothing_point: {   // 跑点 nothing to do
                ROS_INFO_THROTTLE(2, "\033[34marrive goal position,and Pure run point.\033[0m ");
                
                // 确保禁用圆形检测
                std_msgs::Bool detect_disable_msg;
                detect_disable_msg.data = false;
                detect_control_pub_.publish(detect_disable_msg);
                
                // 检查是否需要悬停
                if (waypoint_list[waypoint_next].hover_time > 0.0) {
                    // 开始悬停
                    if (!flag_hover_started) {
                        flag_hover_started = true;
                        hover_start_time = ros::Time::now();
                        current_hover_time = waypoint_list[waypoint_next].hover_time;
                        Drone_mode = Hover;
                        ROS_INFO("\033[33m开始悬停，悬停时间: %.1f 秒\033[0m", current_hover_time);
                    }
                } else {
                    // 不需要悬停，直接前往下一个点
                    NextPoint();
                    have_waypoint_mark = false;
                    Drone_mode= Run_point;
                }
                break;}

            case Land_point: {   // 降落  landing_position
                if(debug&&!flag_land){
                    if(flag_landing_detect) {ROS_INFO_THROTTLE(5, "\033[34mArrive landing position, start detect land mark ...\033[0m  ");}
                    else{ROS_INFO_THROTTLE(5, "\033[34mArrive landing position, and not detect. \033[0m");}
                }
                
                // 确保禁用圆形检测
                std_msgs::Bool detect_disable_msg;
                detect_disable_msg.data = false;
                detect_control_pub_.publish(detect_disable_msg);
                
                Drone_mode= Land;
                if (!flag_landing_detect || LandDetectDone())
                {
                    CallLand();
                    have_land_mark = false;
                    times_detect = 0;
                }
                break;}

            default:
                ROS_INFO_THROTTLE(1, "\033[31m[Error]: unknow  Point_mode \033[0m ");
                break;
        }
    }
    
    // 悬停时间检查
    if (Drone_mode == Hover && flag_hover_started) {
        ros::Time current_time = ros::Time::now();
        double elapsed_hover_time = (current_time - hover_start_time).toSec();
        
        // 显示悬停进度
        if (debug) {
            ROS_INFO_THROTTLE(1, "\033[33m悬停进度: %.1f/%.1f 秒\033[0m", elapsed_hover_time, current_hover_time);
        }
        
        // 悬停时间到，前往下一个点
        if (elapsed_hover_time >= current_hover_time) {
            ROS_INFO("\033[32m悬停完成，前往下一个点\033[0m");
            flag_hover_started = false;
            NextPoint();
            have_waypoint_mark = false;
            Drone_mode = Run_point;
        }
    }
}

void LLController::plannercmdCallback(const geometry_msgs::PoseStamped& msg) {
    have_planner_cmd = true;
    planner_cmd = msg;
}

void LLController::waypointMarkCallback(const geometry_msgs::PoseStamped& msg) {
    have_waypoint_mark = true;
    waypoint_mark = msg;
    ROS_INFO("[PatrolControl] waypoint_mark: %.2f, %.2f, %.2f", waypoint_mark.pose.position.x, waypoint_mark.pose.position.y, waypoint_mark.pose.position.z);
}

void LLController::landMarkCallback(const geometry_msgs::PoseStamped& msg) {
    have_land_mark = true;
    land_mark = msg;
}
bool isQuaternionNormalized(const geometry_msgs::Quaternion& q, double tolerance = 1e-6)
{
    double norm = std::sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
    return std::abs(norm - 1.0) < tolerance;
}
void LLController::servoMarkyCallback(const std_msgs::Bool& msg) {
    servo_marky = msg;
}
void LLController::cmdCallback(const ros::TimerEvent& event) {
    if(!isQuaternionNormalized(uav_pose.pose.orientation)){
        std::cout<<"\033[33m[WARN]: The quaternion of the drone position has not been unitized. Please check whether the position information is correct!\033[0m"<<std::endl;
        return;
    }
    switch(Drone_mode) {
        case Takeoff:  // Takeoff
            have_planner_cmd = false;
            mavros_point_cmd.pose.position.x = takeoff_point[0];
            mavros_point_cmd.pose.position.y = takeoff_point[1];
            mavros_point_cmd.pose.position.z = takeoff_point[2];
            mavros_point_cmd.pose.orientation = tf::createQuaternionMsgFromYaw(waypoint_list[0].yaw);
            ROS_INFO_THROTTLE(5, "Send point to take off ");
            break;

        case Run_point: { // 前往waypoint_list_中的下一个航路点
            // 1. 首先处理正常的航路点导航
            if (current_task_type == MAIN_MISSION) {
                // 正常的航路点导航逻辑
                // 启用途中十字检测（仅在未完成十字投递时）
                if (cross_mark && !cross_drop_completed) {
                    std_msgs::Bool cross_enable_msg;
                    cross_enable_msg.data = true;
                    cross_control_pub_.publish(cross_enable_msg);
                } else if (cross_drop_completed) {
                    // 确保十字检测保持关闭状态
                    std_msgs::Bool cross_disable_msg;
                    cross_disable_msg.data = false;
                    cross_control_pub_.publish(cross_disable_msg);
                }
                
                // 设置目标为当前航路点
                if(!flag_planner_px4){
                    if(have_planner_cmd) mavros_point_cmd = planner_cmd;
                    else mavros_point_cmd = last_mavros_point_cmd;
                }else{
                    mavros_point_cmd = patrol_cmd;
                }
            }
            
            // 2. 检查是否检测到十字（中断主任务）
            if (cross_found_ && current_task_type == MAIN_MISSION && cross_mark && !cross_drop_completed) {
                ROS_INFO("\033[32m[PatrolControl] Cross detected! Starting cross mission interrupt sequence\033[0m");
                
                // 立即禁用十字检测，防止重复触发
                cross_found_ = false;
                
                // 保存当前主任务状态（重点是航路点索引，而不是具体坐标）
                main_mission_mode = Drone_mode;
                mission_interrupted = true;
                
                ROS_INFO("\033[36m[DEBUG] Interrupting mission at waypoint_now=%d, waypoint_next=%d\033[0m", waypoint_now, waypoint_next);
                ROS_INFO("\033[36m[DEBUG] Will resume to continue towards waypoint %d: (%.2f, %.2f, %.2f)\033[0m", 
                         waypoint_next, waypoint_list[waypoint_next].x, waypoint_list[waypoint_next].y, waypoint_list[waypoint_next].z);
                
                // 切换到十字任务
                current_task_type = CROSS_MISSION;
                Drone_mode = Aligning;
                
                // 启用对准系统（alignment_control_converter）用于十字对准
                std_msgs::Bool detect_enable_msg;
                detect_enable_msg.data = true;
                detect_control_pub_.publish(detect_enable_msg);
                
                // 设置十字检测点为当前位置
                setupCrossDetectionPoint();
                
                ROS_INFO("\033[32m[PatrolControl] Cross mission started - alignment_control_converter enabled\033[0m");
            }
            
            // 3. 如果是从十字任务返回，恢复主任务
            if (current_task_type == CROSS_MISSION && cross_mission_completed) {
                ROS_INFO("\033[33m[PatrolControl] Cross mission completed! Cleaning up and resuming main mission\033[0m");
                
                // 首先彻底清理十字任务状态
                current_task_type = MAIN_MISSION;
                mission_interrupted = false;
                cross_mission_completed = false;
                
                // 彻底禁用所有检测系统，避免冲突
                std_msgs::Bool detect_disable_msg;
                detect_disable_msg.data = false;
                detect_control_pub_.publish(detect_disable_msg);
                
                // 永久禁用十字检测，关闭画面显示
                cross_drop_completed = true;
                cross_mark = false;
                std_msgs::Bool cross_disable_msg;
                cross_disable_msg.data = false;
                cross_control_pub_.publish(cross_disable_msg);
                
                // 重置所有检测相关状态，防止残留
                have_waypoint_mark = false;
                times_detect = 0;
                first_call = true;  // 重置WayPointDetectDone的状态
                
                // 恢复主任务：继续前往原来的目标航路点（waypoint_next不变）
                // 不需要设置mavros_point_cmd，让正常的Run_point逻辑处理
                
                ROS_INFO("\033[36m[DEBUG] Resuming mission: waypoint_now=%d, waypoint_next=%d\033[0m", waypoint_now, waypoint_next);
                ROS_INFO("\033[36m[DEBUG] Will continue towards waypoint %d: (%.2f, %.2f, %.2f)\033[0m", 
                         waypoint_next, waypoint_list[waypoint_next].x, waypoint_list[waypoint_next].y, waypoint_list[waypoint_next].z);
                ROS_INFO("\033[36m[PatrolControl] All detection systems disabled, cross detection permanently disabled\033[0m");
                
                // 添加一个短暂的延迟，确保所有状态都已清理
                ros::Duration(0.1).sleep();
            }
            
            ROS_INFO_THROTTLE(5, "Send point to Run_point ");
            break;
        }

        case Hover:   // 悬停状态
            if(!flag_planner_px4){
                if(have_planner_cmd) mavros_point_cmd = planner_cmd;
                else mavros_point_cmd = last_mavros_point_cmd;
            }else{
                mavros_point_cmd = patrol_cmd;
            }
            ROS_INFO_THROTTLE(5, "Send point to Hover ");
            break;

        case Aligning: { // 位置调整 
            have_planner_cmd = false;
            mavros_point_cmd = patrol_cmd;
            
            if (current_task_type == MAIN_MISSION) {
                // 正常航路点的检测对准（原有逻辑）
                ROS_INFO_THROTTLE(5, "Send point to Aligning (Main Mission)");
            }
            else if (current_task_type == CROSS_MISSION) {
                // 十字检测的对准投递
                ROS_INFO_THROTTLE(5, "Send point to Aligning (Cross Mission)");
                
                // 检查十字检测任务是否完成
                if (CrossDetectionDone()) {
                    // 十字任务完成，准备返回主任务
                    cross_mission_completed = true;
                    Drone_mode = Run_point;  // 返回Run_point，会被上面的逻辑处理
                    
                    ROS_INFO("\033[32m[PatrolControl] Cross detection and drop completed!\033[0m");
                }
            }
            break;
        }

        case Land:       // 降落
            have_planner_cmd = false;
            mavros_point_cmd = patrol_cmd;
            if(!flag_land)ROS_INFO_THROTTLE(5, "Send point to Land ");
            break;
    }

    // 计算当前 UAV 位置到目标点的距离
    Eigen::Vector3d current_pos(uav_pose.pose.position.x, uav_pose.pose.position.y, uav_pose.pose.position.z);
    Eigen::Vector3d target_pos(mavros_point_cmd.pose.position.x, mavros_point_cmd.pose.position.y, mavros_point_cmd.pose.position.z);
    double distance_to_target = (target_pos - current_pos).norm();
    // 如果距离超过 px4_max_distance，则进行插值
    if (distance_to_target > px4_max_distance) {
        Eigen::Vector3d direction = (target_pos - current_pos).normalized();
        Eigen::Vector3d new_pos = current_pos + direction * px4_max_distance;
        // 更新目标点为插值后的点位
        mavros_point_cmd.pose.position.x = new_pos.x();
        mavros_point_cmd.pose.position.y = new_pos.y();
        mavros_point_cmd.pose.position.z = new_pos.z();
        ROS_INFO_THROTTLE(2, "Target point adjusted to max distance limit.");
    }

    // 提取当前 yaw 和目标 yaw
    double current_yaw = tf::getYaw(uav_pose.pose.orientation);
    double target_yaw = tf::getYaw(mavros_point_cmd.pose.orientation);

    // 判断 yaw 角插值
    double yaw_diff = target_yaw - current_yaw;
    yaw_diff = atan2(sin(yaw_diff), cos(yaw_diff));  // 确保 yaw_diff 在 [-π, π] 内

    // 限制 yaw 改变量
    if (fabs(yaw_diff) > max_yaw_change) {
        yaw_diff = (yaw_diff > 0) ? max_yaw_change : -max_yaw_change;
        ROS_INFO_THROTTLE(2, "Target point adjusted to max yaw limit.");
    }

    // 插值后的 yaw
    double interpolated_yaw = current_yaw + yaw_diff;
    interpolated_yaw = atan2(sin(interpolated_yaw), cos(interpolated_yaw));  // 归一化到 [-π, π]

    // 将插值后的 yaw 转为四元数
    mavros_point_cmd.pose.orientation.x = 0.0;
    mavros_point_cmd.pose.orientation.y = 0.0;
    mavros_point_cmd.pose.orientation.z = sin(interpolated_yaw / 2.0);
    mavros_point_cmd.pose.orientation.w = cos(interpolated_yaw / 2.0);

    mavros_point_cmd.header.stamp = ros::Time::now();
    mavros_point_cmd.header.frame_id = "camera_init";
    mavros_point_cmd_pub.publish(mavros_point_cmd);
    last_mavros_point_cmd = mavros_point_cmd;
    // 判断是否已经降落，降落成功就锁桨
    if(Drone_mode == Land && uav_pose.pose.position.z <= 0.08){
        Lock();
    }
}

void LLController::Lock() {
    // 准备服务请求
    mavros_msgs::CommandLong cmd;
    cmd.request.broadcast = false;
    cmd.request.command = 400;          // 命令ID
    cmd.request.confirmation = 0;       // 确认
    cmd.request.param1 = 0.0;           // 参数1
    cmd.request.param2 = 21196.0;       // 参数2
    cmd.request.param3 = 0.0;           // 参数3
    cmd.request.param4 = 0.0;           // 参数4
    cmd.request.param5 = 0.0;           // 参数5
    cmd.request.param6 = 0.0;           // 参数6
    cmd.request.param7 = 0.0;           // 参数7
    if(land_client.call(cmd) && cmd.response.success){ROS_INFO_THROTTLE(2, "Vehicle DisArmed!");}
}

void LLController::CallLand() {
    if(auto_land){
        if(!flag_landing_detect){
            adjust_target_position[0] = waypoint_list[waypoint_next].x;
            adjust_target_position[1] = waypoint_list[waypoint_next].y;
        }
        mavros_msgs::SetMode auto_land_mode;
        ros::Duration(2).sleep();
        auto_land_mode.request.custom_mode = "AUTO.LAND";
        if(set_mode_client.call(auto_land_mode) && auto_land_mode.response.mode_sent)
            {ROS_INFO("\033[32m Auto land mode done \033[0m");}
    }else{
        if(!flag_landing_detect){
            adjust_target_position[0] = waypoint_list[waypoint_next].x;
            adjust_target_position[1] = waypoint_list[waypoint_next].y;
            adjust_target_position[3] = waypoint_list[waypoint_next].yaw;
        }
        land_height = -1.0;
    }
    flag_land = true;
}

// 读取launch文件设置的若干个航路点参数
void LLController::load_params() {
    // 开关
    flag_planner_px4 = nh_.param("switch/flag_planner_px4", 1);
    flag_landing_detect = nh_.param("switch/flag_landing_detect", 1);
    auto_land = nh_.param("switch/auto_land", 0);
    // 阈值
    takeoff_threshould = nh_.param("threshould/takeoff_threshould", 0.3);
    planner_min_pub_threshould = nh_.param("threshould/planner_min_pub_threshould", 0.02);
    waypoint_threshould = nh_.param("threshould/waypoint_threshould", 0.3);
    aligning_threshould = nh_.param("threshould/aligning_threshould", 0.15);
    landing_threshould = nh_.param("threshould/landing_threshould", 0.15);
    arrive_yaw_threshould = nh_.param("threshould/arrive_yaw_threshould", 0.3);
    times_detect_threshould = nh_.param("threshould/times_detect_threshould", 30);
    waypoint_adjust_max_second_threshould = nh_.param("threshould/waypoint_adjust_max_second_threshould", 10);
    land_adjust_max_second_threshould = nh_.param("threshould/land_adjust_max_second_threshould", 10);
    // 参数
    land_height = nh_.param("land_height", 0.3);//降落时调整的固定高度
    px4_max_distance = nh_.param("px4_max_distance", 1.2);
    max_yaw_change = nh_.param("max_yaw_change", 0.3);
    
    // 投递系统参数
    drop_precision_threshold = nh_.param("drop_system/precision_threshold", 20.0);
    drop_height_threshold = nh_.param("drop_system/height_threshold", 0.2);
    drop_enabled = nh_.param("drop_system/enable_drop", true);
    descent_stable_duration = nh_.param("drop_system/descent_stable_duration", 2.0);
    
    ROS_INFO("\033[32m[DropSystem] Drop system enabled: %s\033[0m", drop_enabled ? "true" : "false");
    ROS_INFO("\033[32m[DropSystem] Precision threshold: %.1f px\033[0m", drop_precision_threshold);
    ROS_INFO("\033[32m[DropSystem] Height threshold: %.3f m (not used)\033[0m", drop_height_threshold);
    ROS_INFO("\033[32m[DropSystem] Descent stable duration: %.1f s\033[0m", descent_stable_duration);
    
    nh_.getParam("/debug", debug);

    // 从 ROS 参数服务器加载 "waypoints" 参数
    XmlRpc::XmlRpcValue waypoint_list_temp;
    if (nh_.getParam("waypoints", waypoint_list_temp))
    {
        // 确保参数是一个数组类型
        if (waypoint_list_temp.getType() == XmlRpc::XmlRpcValue::TypeArray)
        {
            // 遍历每个路径点
            for (int i = 0; i < waypoint_list_temp.size(); ++i)
            {
                Waypoint wp;
                // 提取路径点的参数
                wp.x = static_cast<double>(waypoint_list_temp[i]["x"]);
                wp.y = static_cast<double>(waypoint_list_temp[i]["y"]);
                wp.z = static_cast<double>(waypoint_list_temp[i]["z"]);
                wp.yaw = static_cast<double>(waypoint_list_temp[i]["yaw"])*3.1415/180;
                wp.pointmode = static_cast<std::string>(waypoint_list_temp[i]["pointmode"]);
                
                // 读取悬停时间，如果没有设置则默认为0
                if (waypoint_list_temp[i].hasMember("hover_time")) {
                    wp.hover_time = static_cast<double>(waypoint_list_temp[i]["hover_time"]);
                } else {
                    wp.hover_time = 0.0;
                }

                // 添加到航路点列表
                waypoint_list.push_back(wp);

                if(debug)ROS_INFO("Loaded waypoint: x=%f, y=%f, z=%f, yaw=%f, pointmode=%s, hover_time=%f",
                            wp.x, wp.y, wp.z, wp.yaw, wp.pointmode.c_str(), wp.hover_time);
            }
        }
    }

    // takeoff point
    takeoff_point[0] = waypoint_list[0].x;
    takeoff_point[1] = waypoint_list[0].y;
    takeoff_point[2] = waypoint_list[0].z;
}

void LLController::pub_goal(geometry_msgs::PoseStamped goal_msg){
    goal_msg.header.frame_id="camera_init";
    goal_msg.header.stamp = ros::Time::now();

    if(!flag_planner_px4){
        // 发送目标点，planner_planner将会控制飞机过去     
        now_pub_point[0] = goal_msg.pose.position.x;
        now_pub_point[1] = goal_msg.pose.position.y;
        now_pub_point[2] = goal_msg.pose.position.z;

        //for send only once
        if ((last_pub_point - now_pub_point).norm() >= planner_min_pub_threshould){
            if(debug)std::cout << "Planner goal_msg:" <<"["<<goal_msg.pose.position.x<<","<<goal_msg.pose.position.y<<","<<goal_msg.pose.position.z<<"]"<<std::endl;
            goal_msg.header.seq +=1;

            setplanner_goal_pub_.publish(goal_msg);
            last_pub_point[0]=goal_msg.pose.position.x;
            last_pub_point[1]=goal_msg.pose.position.y;
            last_pub_point[2]=goal_msg.pose.position.z;
        }
    }else{
        goal_msg.header.seq +=1;
        patrol_cmd = goal_msg;
    }
}

void LLController::NextPoint() {
    // 只在主任务中调用
    if (current_task_type != MAIN_MISSION) {
        ROS_WARN("\033[33m[NextPoint] Called during cross mission, ignoring!\033[0m");
        return;
    }
    
    // 路点指数加一
    waypoint_now = waypoint_next;
    waypoint_next = waypoint_now + 1;
    
    // 确保不超出航路点列表范围
    if(waypoint_next >= waypoint_list.size()){  
        waypoint_next = waypoint_list.size() - 1; 
        ROS_WARN("\033[33m[NextPoint] Reached final waypoint, staying at waypoint %d\033[0m", waypoint_next);
    }
    
    Point_mode = stringToPointmode(waypoint_list[waypoint_next].pointmode);

    // 确保在切换到下一个航路点时禁用圆形检测
    std_msgs::Bool detect_disable_msg;
    detect_disable_msg.data = false;
    detect_control_pub_.publish(detect_disable_msg);
    
    // 重置检测相关状态
    have_waypoint_mark = false;
    times_detect = 0;
    resetDropState();  // 重置投递状态
    resetCrossDetectionState();  // 重置十字检测状态
    
    // 到达新航路点后重新启用十字检测（仅在未完成十字投递时）
    if (!cross_drop_completed) {
        cross_mark = true;
        ROS_INFO("\033[36m[NextPoint] Cross detection enabled for new waypoint\033[0m");
    } else {
        cross_mark = false;
        ROS_INFO("\033[36m[NextPoint] Cross detection remains disabled - already completed\033[0m");
    }

    std::cout<<"\033[32mHave arrive Point number : "<<waypoint_now<<" \nDrone pose now [x ,y, z] : "<<uav_pose.pose.position.x<<", " \
    <<uav_pose.pose.position.y<<", "<<uav_pose.pose.position.z<<std::endl;
    std::cout<<"\033[42;37mNext Point number : "<<waypoint_next<<" ;\n"<<"Next Point Pose: x = "<<waypoint_list[waypoint_next].x<<
    ", y = "<<waypoint_list[waypoint_next].y<<", z = "<<waypoint_list[waypoint_next].z <<" \033[0m"<<std::endl;
    
    // 输出下一个点的模式信息
    std::cout<<"\033[36mNext Point Mode: "<<waypoint_list[waypoint_next].pointmode<<"\033[0m"<<std::endl;
}

bool LLController::WayPointDetectDone()
{
    static ros::Time last_output_time = ros::Time::now();
    double output_interval = 0.2; // 每0.2秒输出一次

    if(first_call)
    {   
        start_time = ros::Time::now();
        first_call = false;
        times_detect = 0;
        ROS_INFO("\033[34m[WayPointDetectDone] Starting detection alignment, resetting detection count\033[0m");
    }

    if(have_waypoint_mark){
        ROS_INFO("\033[32m[WayPointDetectDone] have_waypoint_mark: true");
        // 更新检测目标点
        if(waypoint_mark.pose.position.x == waypoint_mark111.pose.position.x && waypoint_mark.pose.position.y == waypoint_mark111.pose.position.y){
            waypoint_mark.pose.position.x = waypoint_list[waypoint_next].x;
            waypoint_mark.pose.position.y = waypoint_list[waypoint_next].y;
            waypoint_mark.pose.position.z = waypoint_list[waypoint_next].z;
            waypoint_mark.pose.orientation = tf::createQuaternionMsgFromYaw(waypoint_list[waypoint_next].yaw);
        }
        adjust_target_position[0] = waypoint_mark.pose.position.x;  
        adjust_target_position[1] = waypoint_mark.pose.position.y;
        adjust_target_position[2] = waypoint_mark.pose.position.z;
        adjust_target_position[3] = tf::getYaw(waypoint_mark.pose.orientation);
        // 更新检测次数
        times_detect++;
        ROS_INFO("\033[32m[WayPointDetectDone] Received valid target point, detection count: %d\033[0m", times_detect);
        ROS_INFO("\033[32m[WayPointDetectDone] target_x: %.2f, target_y: %.2f", waypoint_mark.pose.position.x, waypoint_mark.pose.position.y);
    }else{
        // 没有目标就发送原始航路点
        adjust_target_position[0] = waypoint_list[waypoint_next].x;
        adjust_target_position[1] = waypoint_list[waypoint_next].y;
        adjust_target_position[2] = waypoint_list[waypoint_next].z;
        adjust_target_position[3] = waypoint_list[waypoint_next].yaw;

        ROS_DEBUG_THROTTLE(2, "\033[33m[WayPointDetectDone] Waiting for valid target point...\033[0m");
        ROS_INFO("\033[32m[WayPointDetectDone] adjust_target_position: %.2f, %.2f", adjust_target_position[0], adjust_target_position[1]);
    }

    // 计算时间进度
    ros::Time current_time = ros::Time::now();
    double elapsed_time = (current_time - start_time).toSec();

    // 防止除零错误
    int clamped_detect_threshould = std::max(1, static_cast<int>(times_detect_threshould));
    double clamped_time_threshould = std::max(0.1f, waypoint_adjust_max_second_threshould);

    // 计算进度比例 [0, 1]
    double detect_progress = std::min(1.0, static_cast<double>(times_detect) / clamped_detect_threshould);
    double time_progress = std::min(1.0, elapsed_time / clamped_time_threshould);

    // 控制输出频率
    if ((current_time - last_output_time).toSec() >= output_interval) {
        last_output_time = current_time;

        // 构建进度条
        int bar_width = 20;
        auto buildProgressBar = [&](double progress) {
            std::string bar = "";
            for (int i = 0; i < bar_width; i++) {
                bar += (i < static_cast<int>(progress * bar_width)) ? "#" : "-";
            }
            return bar;
        };

        std::string detect_bar = buildProgressBar(detect_progress);
        std::string time_bar = buildProgressBar(time_progress);

        std::cout << "\033[36m[WayPointDetectDone] Alignment Progress: [" << detect_bar << "] " << times_detect << "/" << clamped_detect_threshould 
                  << " | Time Progress: [" << time_bar << "] " << elapsed_time << "/" << clamped_time_threshould << " sec\033[0m" 
                  << std::endl;
    }

    // 完成条件：检测次数或时间达到阈值
    if (times_detect >= clamped_detect_threshould || elapsed_time >= clamped_time_threshould) {
        
        // 检查是否满足投递条件
        bool should_drop = false;
        if (checkDropCondition()) {
            // 检查当前检测点是否已经投递过
            if (detect_point_counter < drop_completed.size() && !drop_completed[detect_point_counter]) {
                should_drop = true;
            }
        }
        
        if (should_drop) {
            // 执行投递动作
            int servo_id = detect_point_counter + 1; // 第1个检测点用舵机1，第2个用舵机2，依此类推
            executeDropAction(servo_id);
            
            // 标记当前检测点已完成投递
            drop_completed[detect_point_counter] = true;
            
            ROS_INFO("\033[32m[WayPointDetectDone] Drop completed for detect point %d with servo %d\033[0m", 
                     detect_point_counter + 1, servo_id);
        } else {
            ROS_WARN("\033[33m[WayPointDetectDone] Drop condition not met or already completed for detect point %d\033[0m", 
                     detect_point_counter + 1);
        }
        
        // 更新检测点计数器
        detect_point_counter++;
        
        if (times_detect >= clamped_detect_threshould) {
            ROS_INFO("\033[32m[WayPointDetectDone] Detection count reached threshold (%d/%d), alignment completed\033[0m", 
                     times_detect, clamped_detect_threshould);
        } else {
            ROS_INFO("\033[33m[WayPointDetectDone] Time reached threshold (%.1f/%.1f sec), forcing completion\033[0m", 
                     elapsed_time, clamped_time_threshould);
        }
        
        // 重置状态
        first_call = true;  // 重置标志
        times_detect = 0;
        resetDropState();   // 重置投递状态
        
        // 如果是十字检测触发的对准，完成后需要特殊处理
        
        
        return true;  // 检测完成
    }

    return false;
}


bool LLController::LandDetectDone()
{
    static ros::Time last_output_time = ros::Time::now();
    double output_interval = 0.2; // 每0.5秒输出一次

    if (first_call)
    {   
        start_time = ros::Time::now();
        first_call = false;
        times_detect = 0;
    }

    if(have_land_mark){
        // 更新检测目标点
        adjust_target_position[0] = land_mark.pose.position.x;
        adjust_target_position[1] = land_mark.pose.position.y;
        adjust_target_position[2] = land_height;
        adjust_target_position[3] = tf::getYaw(land_mark.pose.orientation);
        // 更新检测次数
        times_detect++;
        have_land_mark = false;
    }else{
        // 没有目标就发送最后一个着陆点
        adjust_target_position[0] = waypoint_list[waypoint_next].x;
        adjust_target_position[1] = waypoint_list[waypoint_next].y;
        adjust_target_position[2] = land_height;
        adjust_target_position[3] = waypoint_list[waypoint_next].yaw;
    }

    // 计算时间进度
    ros::Time current_time = ros::Time::now();
    double elapsed_time = (current_time - start_time).toSec();

    // 防止除零错误
    int clamped_detect_threshould = std::max(1, static_cast<int>(times_detect_threshould));
    double clamped_time_threshould = std::max(0.1f, land_adjust_max_second_threshould);

    // 计算进度比例 [0, 1]
    double detect_progress = std::min(1.0, static_cast<double>(times_detect) / clamped_detect_threshould);
    double time_progress = std::min(1.0, elapsed_time / clamped_time_threshould);

    // 控制输出频率
    if ((current_time - last_output_time).toSec() >= output_interval) {
        last_output_time = current_time;

        // 构建进度条
        int bar_width = 20;
        auto buildProgressBar = [&](double progress) {
            std::string bar = "";
            for (int i = 0; i < bar_width; i++) {
                bar += (i < static_cast<int>(progress * bar_width)) ? "#" : "-";
            }
            return bar;
        };

        std::string detect_bar = buildProgressBar(detect_progress);
        std::string time_bar = buildProgressBar(time_progress);

        if(!flag_land)std::cout << "Landing Progress: [" << detect_bar << "] " << times_detect << "/" << clamped_detect_threshould 
                  << " | Time Progress: [" << time_bar << "] " << elapsed_time << "/" << clamped_time_threshould << " sec" 
                  << std::endl;
    }

    // 完成条件：检测次数或时间达到阈值
    if (times_detect >= clamped_detect_threshould || elapsed_time >= clamped_time_threshould) {
        first_call = true;  // 重置标志
        times_detect = 0;
        return true;  // 降落检测完成
    }

    return false;
}

// 投递相关函数实现
void LLController::alignmentFeedbackCallback(const geometry_msgs::Point::ConstPtr& msg) {
    // 获取像素偏差信息
    current_pixel_error = sqrt(msg->x * msg->x + msg->y * msg->y);
    
    // 获取当前目标高度
    double current_target_height = adjust_target_position[2];
    
    // 检测渐进降高是否完成（使用成员变量，避免static污染）
    ros::Time current_time = ros::Time::now();
    double height_change = abs(current_target_height - last_target_height_);
    
    // 如果目标高度变化很小（小于1cm），认为高度稳定
    if (height_change < 0.01) {
        // 目标高度稳定
        if (!descent_completed) {
            // 第一次检测到稳定，记录开始时间
            if ((current_time - last_check_time_).toSec() > 0.5) { // 每0.5秒检查一次
                if (final_target_height == 0.0) {
                    descent_stable_start_time = current_time;
                    final_target_height = current_target_height;
                    ROS_INFO("\033[1;33m[DropSystem] Target height stabilized at %.3f m, monitoring stability...\033[0m", 
                             final_target_height);
                }
                
                // 检查是否稳定足够长时间
                double stable_duration = (current_time - descent_stable_start_time).toSec();
                if (stable_duration >= descent_stable_duration) {
                    descent_completed = true;
                    ROS_INFO("\033[1;32m[DropSystem] Progressive descent completed! Final height: %.3f m\033[0m", 
                             final_target_height);
                }
                last_check_time_ = current_time;
            }
        }
    } else {
        // 目标高度还在变化，重置状态
        if (descent_completed) {
            ROS_WARN("\033[1;33m[DropSystem] Target height changed, resetting descent completion status\033[0m");
        }
        descent_completed = false;
        final_target_height = 0.0;
        last_check_time_ = current_time;
    }
    
    last_target_height_ = current_target_height;
    
    // 定期输出对准状态（移除高度误差显示）
    ROS_INFO_THROTTLE(0.5, "\033[36m[DropSystem] Pixel: %.1fpx, Descent: %s\033[0m", 
                      current_pixel_error, descent_completed ? "COMPLETED" : "IN_PROGRESS");
}

bool LLController::checkDropCondition() {
    // 首先检查投递功能是否启用
    if (!drop_enabled) {
        ROS_DEBUG_THROTTLE(2, "\033[33m[DropSystem] Drop system disabled\033[0m");
        return false;
    }
    
    // 检查渐进降高是否完成
    if (!descent_completed) {
        ROS_DEBUG_THROTTLE(1, "\033[33m[DropSystem] Waiting for progressive descent to complete\033[0m");
        return false;
    }
    
    // 只检查像素精度是否满足投递条件（移除高度误差判断）
    bool pixel_ok = current_pixel_error < drop_precision_threshold;
    
    if (servo_marky.data) {
        ROS_INFO("\033[32m[DropSystem] Drop condition met! Pixel: %.1f/%.1f, Descent: COMPLETED\033[0m", 
                 current_pixel_error, drop_precision_threshold);
        return true;
    } else {
        ROS_DEBUG_THROTTLE(1, "\033[33m[DropSystem] Precision not met - Pixel: %.1f/%.1f\033[0m", 
                           current_pixel_error, drop_precision_threshold);
    }
    
    return false;
}

void LLController::executeDropAction(int servo_id) {
    if (servo_id < 1 || servo_id > 3) {
        ROS_ERROR("\033[31m[DropSystem] Invalid servo ID: %d\033[0m", servo_id);
        return;
    }
    
    // 创建投递控制消息
    std_msgs::Bool drop_msg;
    drop_msg.data = true;
    
    // 选择对应的舵机发布器
    ros::Publisher* servo_pub = nullptr;
    std::string topic_name;
    
    switch (servo_id) {
        case 1:
            servo_pub = &servo1_pub_;
            topic_name = "/control1";
            break;
        case 2:
            servo_pub = &servo2_pub_;
            topic_name = "/control2";
            break;
        case 3:
            servo_pub = &servo3_pub_;
            topic_name = "/control3";
            break;
        default:
            ROS_ERROR("\033[31m[DropSystem] Invalid servo ID: %d\033[0m", servo_id);
            return;
    }
    
    ROS_INFO("\033[32m[DropSystem] Executing drop action for servo %d\033[0m", servo_id);
    ROS_INFO("\033[32m[DropSystem] Publishing to topic: %s\033[0m", topic_name.c_str());
    
    // 发布投递命令，重复发布几次确保接收
    for (int i = 0; i < 5; i++) {
        servo_pub->publish(drop_msg);
        ros::Duration(0.1).sleep();  // 间隔100ms
    }
    
    ROS_INFO("\033[32m[DropSystem] Drop action %d completed successfully\033[0m", servo_id);
}

void LLController::resetDropState() {
    drop_condition_met = false;
    current_pixel_error = 1000.0;
    descent_completed = false;
    final_target_height = 0.0;
    last_target_height_ = 0.0;
    last_check_time_ = ros::Time::now();
    ROS_DEBUG("\033[36m[DropSystem] Drop state reset for next detection point\033[0m");
}

// 十字检测相关函数实现
void LLController::crossPixelOffsetCallback(const geometry_msgs::Point::ConstPtr& msg) {
    cross_pixel_offset_ = *msg;
    cross_found_ = true;
    
    ROS_INFO_THROTTLE(1.0, "\033[35m[PatrolControl] Cross pixel offset: (%.1f, %.1f, radius=%.1f)\033[0m", 
                      msg->x, msg->y, msg->z);
    
    // 这里可以根据十字检测结果调整巡检策略
    // 例如：如果检测到十字，可以触发特殊的对准或降落模式
}

void LLController::crossCenterCallback(const geometry_msgs::Point::ConstPtr& msg) {
    cross_center_ = *msg;
    
    ROS_INFO_THROTTLE(1.0, "\033[35m[PatrolControl] Cross center: (%.1f, %.1f, area=%.1f)\033[0m", 
                      msg->x, msg->y, msg->z);
}

void LLController::crossStatusCallback(const std_msgs::Bool::ConstPtr& msg) {
    static bool last_state = false;
    static bool first_call = true;
    
    bool new_state = msg->data;
    
    // 只在状态变化时输出提示
    if (first_call || new_state != last_state) {
        if (new_state) {
            ROS_INFO("\033[32m[PatrolControl] Cross detection: RED CROSS FOUND!\033[0m");
        } else {
            ROS_INFO("\033[33m[PatrolControl] Cross detection: RED CROSS LOST\033[0m");
        }
        last_state = new_state;
        first_call = false;
    }
    
    cross_detection_active_ = new_state;
    cross_found_ = new_state;
}

void LLController::enableCrossDetection(bool enable) {
    std_msgs::Bool cross_control_msg;
    cross_control_msg.data = enable;
    cross_control_pub_.publish(cross_control_msg);
    
    if (enable) {
        ROS_INFO("\033[32m[PatrolControl] Cross detection ENABLED\033[0m");
    } else {
        ROS_INFO("\033[33m[PatrolControl] Cross detection DISABLED\033[0m");
    }
}

void LLController::crossStateCallback(const std_msgs::Bool::ConstPtr& msg) {
    // 这个函数可以用于处理外部的十字状态控制信号
    cross_found_ = msg->data;
    
    if (msg->data) {
        ROS_INFO("\033[35m[PatrolControl] External cross state: CROSS DETECTED\033[0m");
    } else {
        ROS_INFO("\033[35m[PatrolControl] External cross state: CROSS CLEARED\033[0m");
    }
}

// 新增任务管理函数实现
bool LLController::CrossDetectionDone() {
    // 使用与圆环检测相同的逻辑，通过alignment_control_converter进行精确对准
    static ros::Time cross_start_time = ros::Time::now();
    static bool cross_first_call = true;
    static int cross_detect_times = 0;
    static ros::Time last_output_time = ros::Time::now();
    double output_interval = 0.2; // 每0.2秒输出一次
    
    if (cross_first_call) {
        cross_start_time = ros::Time::now();
        cross_first_call = false;
        cross_detect_times = 0;
        ROS_INFO("\033[34m[CrossDetection] Starting cross alignment using alignment_control_converter\033[0m");
    }
    
    if (have_waypoint_mark) {
        // 使用与圆环检测相同的逻辑：接收alignment_control_converter的精确对准结果
        adjust_target_position[0] = waypoint_mark.pose.position.x;
        adjust_target_position[1] = waypoint_mark.pose.position.y;
        adjust_target_position[2] = waypoint_mark.pose.position.z;  // 使用alignment_control_converter计算的高度
        adjust_target_position[3] = tf::getYaw(waypoint_mark.pose.orientation);
        
        cross_detect_times++;
        ROS_INFO("\033[32m[CrossDetection] Received alignment target, detection count: %d\033[0m", cross_detect_times);
    } else {
        // 没有对准目标时，保持在十字检测点
        // 注意：这里不设置原始航路点，因为我们是在进行十字检测
        ROS_DEBUG_THROTTLE(2, "\033[33m[CrossDetection] Waiting for alignment target from alignment_control_converter...\033[0m");
    }
    
    // 计算时间进度
    ros::Time current_time = ros::Time::now();
    double elapsed_time = (current_time - cross_start_time).toSec();
    
    // 使用与圆环检测相同的阈值参数
    int clamped_detect_threshould = std::max(1, static_cast<int>(times_detect_threshould));
    double clamped_time_threshould = std::max(0.1f, waypoint_adjust_max_second_threshould);
    
    // 计算进度比例 [0, 1]
    double detect_progress = std::min(1.0, static_cast<double>(cross_detect_times) / clamped_detect_threshould);
    double time_progress = std::min(1.0, elapsed_time / clamped_time_threshould);
    
    // 控制输出频率（与圆环检测相同的进度条显示）
    if ((current_time - last_output_time).toSec() >= output_interval) {
        last_output_time = current_time;

        // 构建进度条
        int bar_width = 20;
        auto buildProgressBar = [&](double progress) {
            std::string bar = "";
            for (int i = 0; i < bar_width; i++) {
                bar += (i < static_cast<int>(progress * bar_width)) ? "#" : "-";
            }
            return bar;
        };

        std::string detect_bar = buildProgressBar(detect_progress);
        std::string time_bar = buildProgressBar(time_progress);

        std::cout << "\033[35m[CrossDetection] Alignment Progress: [" << detect_bar << "] " << cross_detect_times << "/" << clamped_detect_threshould 
                  << " | Time Progress: [" << time_bar << "] " << elapsed_time << "/" << clamped_time_threshould << " sec\033[0m" 
                  << std::endl;
    }
    
    // 完成条件：检测次数或时间达到阈值（与圆环检测相同）
    if (cross_detect_times >= clamped_detect_threshould || elapsed_time >= clamped_time_threshould) {
        
        // 使用与圆环检测相同的投递条件检查
        bool should_drop = false;
        if (checkDropCondition()) {
            should_drop = true;
        }
        
        if (should_drop) {
            // 执行十字投递动作
            executeDropAction(cross_servo_id);
            
            ROS_INFO("\033[32m[CrossDetection] Cross drop completed with servo %d\033[0m", cross_servo_id);
        } else {
            ROS_WARN("\033[33m[CrossDetection] Drop condition not met for cross detection\033[0m");
        }
        
        if (cross_detect_times >= clamped_detect_threshould) {
            ROS_INFO("\033[32m[CrossDetection] Detection count reached threshold (%d/%d), cross alignment completed\033[0m", 
                     cross_detect_times, clamped_detect_threshould);
        } else {
            ROS_INFO("\033[33m[CrossDetection] Time reached threshold (%.1f/%.1f sec), forcing completion\033[0m", 
                     elapsed_time, clamped_time_threshould);
        }
        
        // 重置状态，确保彻底清理
        cross_first_call = true;
        cross_detect_times = 0;
        //have_waypoint_mark = false;
        
        // 重置alignment_control_converter的状态
        times_detect = 0;
        
        ROS_INFO("\033[32m[CrossDetection] Cross detection task completed, all states reset\033[0m");
        return true;  // 十字检测完成
    }
    return false;
}

void LLController::setupCrossDetectionPoint() {
    // 将当前位置设为十字检测点
    geometry_msgs::PoseStamped cross_waypoint_mark;
    cross_waypoint_mark.header.stamp = ros::Time::now();
    cross_waypoint_mark.header.frame_id = "map";
    cross_waypoint_mark.pose.position.x = uav_pose.pose.position.x;
    cross_waypoint_mark.pose.position.y = uav_pose.pose.position.y;
    cross_waypoint_mark.pose.position.z = uav_pose.pose.position.z;
    cross_waypoint_mark.pose.orientation = uav_pose.pose.orientation;
    
    waypoint_mark = cross_waypoint_mark;
    have_waypoint_mark = true;
    
    ROS_INFO("\033[33m[CrossDetection] Cross waypoint set at: (%.2f, %.2f, %.2f)\033[0m", 
             waypoint_mark.pose.position.x, waypoint_mark.pose.position.y, waypoint_mark.pose.position.z);
}

void LLController::resetCrossDetectionState() {
    cross_found_ = false;           // 重置检测状态
    cross_mission_completed = false;
    cross_detection_active_ = false;
    // cross_mark保持状态，由NextPoint控制
    
    ROS_DEBUG("\033[36m[CrossDetection] Cross detection state reset\033[0m");
}

}
