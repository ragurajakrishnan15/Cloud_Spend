view: daily_spend {
  sql_table_name: CLOUDSPEND_AI.REPORTING.VW_DAILY_CLOUD_SPEND ;;

  dimension_group: usage {
    type: time
    timeframes: [date, week, month, quarter, year]
    datatype: date
    sql: ${TABLE}.USAGE_DATE ;;
  }
  dimension: is_weekend { type: yesno sql: ${TABLE}.IS_WEEKEND ;; }
  dimension: department_name { type: string sql: ${TABLE}.DEPARTMENT_NAME ;; }
  dimension: service_name { type: string sql: ${TABLE}.SERVICE_NAME ;; }
  dimension: environment_name { type: string sql: ${TABLE}.ENVIRONMENT_NAME ;; }
  dimension: region_name { type: string sql: ${TABLE}.REGION_NAME ;; }

  measure: total_cost {
    type: sum
    sql: ${TABLE}.TOTAL_COST ;;
    value_format_name: usd_0
    description: "SUM(total_cost) for the selected slice."
  }
  measure: usage_units { type: sum sql: ${TABLE}.USAGE_UNITS ;; }
  measure: days_with_data { type: count_distinct sql: ${TABLE}.USAGE_DATE ;; }
  measure: avg_daily_cost {
    type: number
    sql: ${total_cost} / NULLIF(${days_with_data}, 0) ;;
    value_format_name: usd
    description: "Total cost / distinct days with data. Ratios are computed from sums, never averaged."
  }
}
