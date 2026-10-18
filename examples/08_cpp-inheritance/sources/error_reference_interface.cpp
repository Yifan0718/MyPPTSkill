// Expected compile failure: name lookup uses the static type Base.
struct Base { int id = 7; };
struct Derived : Base { int score = 90; };
int main() { Derived d; Base& r = d; return r.score; }
