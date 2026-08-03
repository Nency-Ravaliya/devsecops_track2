resource "random_integer" "rnd_int" {
  min     = 1
  max     = 10000
}

resource "random_string" "password" {
  length  = 16
  special = true
}
