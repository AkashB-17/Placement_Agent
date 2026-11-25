/** Who students contact to correct their academic record. Change it here only. */
export const PLACEMENT_CONTACT = {
  email: "Bhanu.Dwivedi@bennett.edu.in",
  phone: "+91 8116754740",
} as const;

/** The phone number as a tel: link (digits and the leading +, no spaces). */
export const placementPhoneHref = `tel:${PLACEMENT_CONTACT.phone.replace(/[^\d+]/g, "")}`;
