# Additional discovery for developer feedback only. Existing acceptance jobs
# keep their default CTest inventory and all explicit negative target routes.
option(SC_DEVELOPER_CONTEXT "Register the developer feedback context" OFF)
if(SC_DEVELOPER_CONTEXT)
  foreach(sc_group sizes text bytes lists maps errors cleanup)
    add_test(NAME foundation.${sc_group} COMMAND foundation_contracts ${sc_group})
    set_tests_properties(foundation.${sc_group} PROPERTIES LABELS "foundation;developer")
  endforeach()
  add_test(NAME foundation.retain-accounting COMMAND foundation_contracts retain-accounting)
  add_test(NAME foundation.recipes COMMAND foundation_recipes)
  set_tests_properties(foundation.retain-accounting foundation.recipes
                      PROPERTIES LABELS "foundation;developer")
endif()
