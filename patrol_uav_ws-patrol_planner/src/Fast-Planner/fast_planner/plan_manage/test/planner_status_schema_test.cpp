#include <gtest/gtest.h>
#include <ros/serialization.h>

#include <plan_manage/PlannerStatus.h>

#include <vector>

TEST(PlannerStatusSchema, StatusValuesRemainStable) {
  EXPECT_EQ(0u, plan_manage::PlannerStatus::ACCEPTED);
  EXPECT_EQ(1u, plan_manage::PlannerStatus::PLANNING);
  EXPECT_EQ(2u, plan_manage::PlannerStatus::TRAJECTORY_READY);
  EXPECT_EQ(3u, plan_manage::PlannerStatus::REPLANNING);
  EXPECT_EQ(4u, plan_manage::PlannerStatus::TRAJECTORY_FINISHED);
  EXPECT_EQ(5u, plan_manage::PlannerStatus::FAILED_ATTEMPT);
  EXPECT_EQ(6u, plan_manage::PlannerStatus::CANCELLED);
}

TEST(PlannerStatusSchema, CorrelationAndGoalsSurviveSerialization) {
  plan_manage::PlannerStatus source;
  source.header.seq                = 9;
  source.event_seq                 = 9;
  source.goal_seq                  = 42;
  source.status                    = plan_manage::PlannerStatus::REPLANNING;
  source.planning_attempt          = 3;
  source.requested_goal.header.seq = 42;
  source.requested_goal.pose.position.x = 1.0;
  source.effective_goal.header.seq = 42;
  source.effective_goal.pose.position.x = 1.25;
  source.distance_to_goal          = 0.75;
  source.reason                    = "effective_goal_adjusted";

  const uint32_t length = ros::serialization::serializationLength(source);
  std::vector<uint8_t> buffer(length);
  ros::serialization::OStream output(buffer.data(), length);
  ros::serialization::serialize(output, source);

  plan_manage::PlannerStatus restored;
  ros::serialization::IStream input(buffer.data(), length);
  ros::serialization::deserialize(input, restored);

  EXPECT_EQ(source.event_seq, restored.event_seq);
  EXPECT_EQ(source.goal_seq, restored.goal_seq);
  EXPECT_EQ(source.status, restored.status);
  EXPECT_EQ(source.planning_attempt, restored.planning_attempt);
  EXPECT_EQ(source.requested_goal.header.seq, restored.requested_goal.header.seq);
  EXPECT_DOUBLE_EQ(source.requested_goal.pose.position.x,
                   restored.requested_goal.pose.position.x);
  EXPECT_DOUBLE_EQ(source.effective_goal.pose.position.x,
                   restored.effective_goal.pose.position.x);
  EXPECT_DOUBLE_EQ(source.distance_to_goal, restored.distance_to_goal);
  EXPECT_EQ(source.reason, restored.reason);
}

int main(int argc, char** argv) {
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
