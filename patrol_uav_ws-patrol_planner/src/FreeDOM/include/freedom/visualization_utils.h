#ifndef FREEDOM_VISUALIZATION_UTILS_H
#define FREEDOM_VISUALIZATION_UTILS_H

#include <cmath>

namespace freedom {

class PublishThrottle
{
public:
    explicit PublishThrottle(double max_rate_hz = 0.5)
    {
        configure(max_rate_hz);
    }

    void configure(double max_rate_hz)
    {
        enabled_ = std::isfinite(max_rate_hz) && max_rate_hz > 0.0;
        min_interval_sec_ = enabled_ ? 1.0 / max_rate_hz : 0.0;
        initialized_ = false;
        last_publish_sec_ = 0.0;
    }

    bool should_publish(double now_sec)
    {
        if(!enabled_ || !std::isfinite(now_sec))
            return false;

        if(!initialized_ || now_sec < last_publish_sec_ ||
           now_sec - last_publish_sec_ + 1e-9 >= min_interval_sec_)
        {
            initialized_ = true;
            last_publish_sec_ = now_sec;
            return true;
        }

        return false;
    }

private:
    bool enabled_ = false;
    bool initialized_ = false;
    double min_interval_sec_ = 0.0;
    double last_publish_sec_ = 0.0;
};

}  // namespace freedom

#endif
