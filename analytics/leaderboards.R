library(dplyr)
library(ggplot2)


sightings <- tbl(con, "sightings")
contributors <- tbl(con, "contributors")

sightings |> 
  group_by(contributor_id) |>
  summarise(
    sighting_count = n()
  ) |>
  left_join(contributors, by.x contributor_id = contributors_id")
  ggplot()
  
