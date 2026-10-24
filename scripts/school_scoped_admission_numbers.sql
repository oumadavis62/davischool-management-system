-- Allow different schools to reuse admission numbers while preventing duplicates within a school.
-- Case-insensitive to match the application-level validation.
ALTER TABLE public.students
    DROP CONSTRAINT IF EXISTS students_admission_no_key;

CREATE UNIQUE INDEX IF NOT EXISTS students_school_admission_no_lower_uidx
    ON public.students (school_id, lower(trim(admission_no)))
    WHERE admission_no IS NOT NULL AND trim(admission_no) <> '';
