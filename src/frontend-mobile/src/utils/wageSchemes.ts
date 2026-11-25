export function canEnterWageSchemes(hasPermission: (permission: string) => boolean) {
  return hasPermission('workshop_reporting.view_wagescheme')
    && hasPermission('workshop_reporting.submit_wagescheme')
    && (hasPermission('workshop_reporting.add_wagescheme') || hasPermission('workshop_reporting.change_wagescheme'))
}
