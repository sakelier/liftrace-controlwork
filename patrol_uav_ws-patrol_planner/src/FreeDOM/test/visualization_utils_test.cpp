#include <gtest/gtest.h>

#include <limits>

#include "freedom/visualization_utils.h"

namespace freedom {

TEST(PublishThrottleTest, EnforcesConfiguredMaximumRate)
{
    PublishThrottle throttle(0.5);

    EXPECT_TRUE(throttle.should_publish(10.0));
    EXPECT_FALSE(throttle.should_publish(11.999));
    EXPECT_TRUE(throttle.should_publish(12.0));
    EXPECT_FALSE(throttle.should_publish(13.0));
    EXPECT_TRUE(throttle.should_publish(14.0));
}

TEST(PublishThrottleTest, RecoversFromWallClockRegression)
{
    PublishThrottle throttle(1.0);

    EXPECT_TRUE(throttle.should_publish(20.0));
    EXPECT_TRUE(throttle.should_publish(5.0));
    EXPECT_FALSE(throttle.should_publish(5.5));
    EXPECT_TRUE(throttle.should_publish(6.0));
}

TEST(PublishThrottleTest, RejectsDisabledAndInvalidTime)
{
    PublishThrottle disabled(0.0);
    EXPECT_FALSE(disabled.should_publish(1.0));

    PublishThrottle throttle(1.0);
    EXPECT_FALSE(throttle.should_publish(std::numeric_limits<double>::quiet_NaN()));
    EXPECT_TRUE(throttle.should_publish(1.0));
}

}  // namespace freedom

int main(int argc, char** argv)
{
    testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
