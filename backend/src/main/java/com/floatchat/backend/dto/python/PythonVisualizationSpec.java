package com.floatchat.backend.dto.python;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PythonVisualizationSpec(
    @JsonProperty("chart_type") String chartType,
    @JsonProperty("x_axis") String xAxis,
    @JsonProperty("y_axis") String yAxis,
    @JsonProperty("title") String title,
    @JsonProperty("invert_y") Boolean invertY,
    @JsonProperty("series_column") String seriesColumn,
    @JsonProperty("description") String description,
    @JsonProperty("data") List<Map<String, Object>> data
) {
}
