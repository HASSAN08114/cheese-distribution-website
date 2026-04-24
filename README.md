# Cheese Distribution Management System

A complete, professional Django web application for managing a cheese distribution business with role-based access control and modern UI.

## ✨ Features

### Core Features
- **Manufacturer Management** - Manage cheese manufacturers and suppliers
- **Cheese Inventory Management** - Track cheese products, stock levels, and purchase prices
- **Client Management** - Manage customer information (name, phone, address)
- **Sale Creation & Tracking** - Create sales with automatic stock deduction
- **Automatic Profit Calculation** - Real-time profit calculation for each sale
- **Stock Management** - Automatic stock deduction when sales are made
- **Dashboard** - Comprehensive business statistics and overview

### New Features (Latest Update)
- **Role-Based Access Control** - Two user types:
  - **Owner**: Full access to all features including sensitive data, inventory management, and client deletion
  - **Employee/Receptionist**: Limited access to add clients, create sales, and view sales history
- **Merged Inventory Page** - Manufacturers and Cheese Inventory combined into one easy-to-use page
- **Sales Analytics** - View daily, monthly, and yearly sales with profit breakdowns
- **Modern UI/UX** - Beautiful, user-friendly interface with icons and improved design
- **Simplified Client Management** - Removed email field for easier data entry

## 🚀 Setup Instructions

1. **Install Python 3.8 or higher**

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment:**
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```
   - On Linux/Mac:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run migrations:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

   
# Data Restoration
   ```bash
   py manage.py loaddata file
   ```
   Maybe do a sequence reset.
   
6. **Create a superuser account:**
   ```bash
   python manage.py createsuperuser
   ```

7. **Set user roles:**
   After creating users, set their roles using the management command:
   ```bash
   # Set a user as owner
   python manage.py set_user_role <username> owner
   
   # Set a user as employee
   python manage.py set_user_role <username> employee
   ```
   
   **Note:** New users are automatically set as employees by default. Only owners can access inventory management and delete clients.

8. **Run the development server:**
   ```bash
   python manage.py runserver
   ```

9. **Access the application:**
   - Open your browser and go to `http://127.0.0.1:8000/`
   - Login with your credentials

10. **(Optional) Populate test data:**
    ```bash
    python populate_test_data.py
    ```
    This creates sample manufacturers, cheese products, and clients for testing.

## 👥 User Roles

### Owner
- Full access to all features
- Can manage inventory (manufacturers and cheese products)
- Can delete clients
- Can view all sensitive business data
- Access to complete dashboard

### Employee/Receptionist
- Can add and edit clients
- Can create sales
- Can view sales history and analytics
- Cannot access inventory management
- Cannot delete clients
- Limited access to sensitive data

## 📊 Sales Analytics

The Sales page now includes:
- **Daily Sales**: Today's total sales and profit
- **Monthly Sales**: Current month's total sales and profit
- **Yearly Sales**: Current year's total sales and profit
- **Complete Sale History**: All sales with detailed information

## 🗄️ Database

- **Default**: Uses SQLite (db.sqlite3) - perfect for development and small deployments
- **Production**: Can easily switch to PostgreSQL using environment variables
- See `database_config.md` for detailed PostgreSQL setup instructions

### To use PostgreSQL:
1. Install PostgreSQL and create a database
2. Set environment variables:
   - Windows:
     ```bash
     set USE_SQLITE=False
     set DB_NAME=cheese_distribution
     set DB_USER=your_username
     set DB_PASSWORD=your_password
     ```
   - Linux/Mac:
     ```bash
     export USE_SQLITE=False
     export DB_NAME=cheese_distribution
     export DB_USER=your_username
     export DB_PASSWORD=your_password
     ```
3. Run migrations: `python manage.py migrate`

## 📁 Project Structure

```
cheese distribution website/
├── cheese_distribution/     # Main project directory
│   ├── settings.py         # Django settings
│   ├── urls.py             # Main URL configuration
│   └── ...
├── distribution/           # Main application directory
│   ├── models.py           # Database models
│   ├── views.py            # View functions
│   ├── forms.py            # Form classes
│   ├── urls.py             # URL routing
│   ├── decorators.py       # Role-based access decorators
│   ├── context_processors.py  # Template context
│   ├── signals.py          # Django signals
│   ├── management/         # Management commands
│   │   └── commands/
│   │       └── set_user_role.py
│   └── templates/          # HTML templates
│       └── distribution/
├── static/                 # Static files (CSS, JS)
│   └── css/
│       └── style.css
├── manage.py               # Django management script
└── requirements.txt        # Python dependencies
```

## 🎨 UI Improvements

- Modern gradient backgrounds
- Responsive design for mobile and desktop
- Icon-based navigation
- Color-coded status badges
- Improved form layouts
- Better visual hierarchy
- Smooth animations and transitions

## 🔒 Security Features

- Role-based access control
- CSRF protection
- Secure session management
- Password validation
- Protected views with authentication

## 📝 Notes

- All new users are automatically assigned the "employee" role
- Use the `set_user_role` management command to change user roles
- Owners have full access; employees have limited access as described above
- The inventory management page combines manufacturers and cheese products for easier management

## 🆘 Troubleshooting

If you encounter issues:
1. Make sure all migrations are applied: `python manage.py migrate`
2. Check that you've set user roles correctly
3. Verify your database connection settings
4. Check the Django console for error messages

## 📄 License

This project is ready for handover and deployment.

