# CloudSpend AI - LookML model over the Snowflake REPORTING views (all data is synthetic).
# Set the connection name to your own Looker->Snowflake connection. Point it at a READ-ONLY role (CLOUDSPEND_READER,
# see sql/08_readonly_role.sql). This project has not been run against a live Looker instance; validate it in the Looker IDE.
connection: "cloudspend_snowflake"

include: "/views/*.view.lkml"

explore: daily_spend {
  label: "Daily cloud spend"
  description: "Grain: day x department x service x environment x region."
}

explore: budget_variance {
  label: "Budget variance"
  description: "Grain: month x department x service. Budgets exist only at this grain - do not slice by environment or region."
}

explore: cost_anomalies {
  label: "Cost anomalies"
  description: "Statistical flags relative to a baseline. A flag is not evidence of fraud or a confirmed cost problem."
}
