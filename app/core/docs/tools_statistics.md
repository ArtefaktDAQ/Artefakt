# Statistics Dashboard

The Statistics tool provides deep mathematical insight into your live sensor data. It's used for quality control, stability testing, and noise analysis.

## Real-Time Metrics

- **Mean/Median**: Central tendency of the data. Large differences suggest outliers.
- **Min/Max/Range**: The absolute limits of the data window.
- **Standard Deviation (Std Dev)**: A measure of noise or signal stability.
- **Coefficient of Variation (CV)**: Relative noise level (Std Dev / Mean). Great for comparing noise across different types of sensors.
- **Trend**: Directional analysis (Increasing, Decreasing, or Stable).

## Visualizations

### Histogram
Shows the distribution of values.
- **Normal Distribution**: A bell curve shape, typical for stable physical processes.
- **Bimodal**: Two peaks, suggesting the system is switching between two states.
- **Skewed**: Indicates a bias or a physical limit being reached.

### Trend Analysis
Calculates the slope of the data over time to determine if the process is drifting.

## Advanced Metrics

- **IQR (Interquartile Range)**: The spread of the middle 50% of data. More robust than Range.
- **Skewness**: Measure of asymmetry.
- **Kurtosis**: Measure of "peakedness" vs. flatness of the distribution.

## Best Practices

- **Sample Size**: Let the tool collect data for a few seconds to get reliable statistics.
- **Outlier Detection**: Use the Histogram to spot random spikes that might be skewing your Mean.
- **Stability Check**: Use the Standard Deviation to quantify how much "jitter" is in your system.
