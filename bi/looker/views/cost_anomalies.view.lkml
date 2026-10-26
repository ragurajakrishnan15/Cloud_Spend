view: cost_anomalies {
  sql_table_name: CLOUDSPEND_AI.REPORTING.VW_COST_ANOMALIES ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: ${TABLE}.RECORD_ID || '|' || ${TABLE}.DETECTION_METHOD ;;
  }
  dimension: record_id { type: string sql: ${TABLE}.RECORD_ID ;; }
  dimension_group: usage {
    type: time
    timeframes: [date, week, month]
    datatype: date
    sql: ${TABLE}.USAGE_DATE ;;
  }
  dimension: department_name { type: string sql: ${TABLE}.DEPARTMENT_NAME ;; }
  dimension: service_name { type: string sql: ${TABLE}.SERVICE_NAME ;; }
  dimension: environment_name { type: string sql: ${TABLE}.ENVIRONMENT_NAME ;; }
  dimension: detection_method { type: string sql: ${TABLE}.DETECTION_METHOD ;; }
  dimension: severity { type: string sql: ${TABLE}.SEVERITY ;; }
  dimension: reason { type: string sql: ${TABLE}.REASON ;; }

  measure: flagged_records {
    type: count_distinct
    sql: ${TABLE}.RECORD_ID ;;
    description: "Distinct flagged records (a record flagged by two methods counts once)."
  }
  measure: observed_cost { type: sum sql: ${TABLE}.OBSERVED_COST ;; value_format_name: usd_0 }
  measure: baseline_cost { type: sum sql: ${TABLE}.BASELINE_COST ;; value_format_name: usd_0 }
  measure: excess_over_baseline {
    type: number
    sql: ${observed_cost} - ${baseline_cost} ;;
    value_format_name: usd_0
    description: "Sum of observed - sum of baseline. Filter to a single detection method to avoid double counting records flagged by both."
  }
}
